--- START OF FILE internal/manage/tlsconf.go ---
package manage

import (
	"crypto/tls"
	"fmt"
	"os"
	"sync"
	"time"

	"golang.org/x/crypto/acme"
	"golang.org/x/crypto/acme/autocert"
)

// TLS configuration for the wss and wssmux transports.
//
// Two ways to get a certificate:
//
//   - A file pair on disk, which is the self-signed certificate ParsTanel
//     generates. This works anywhere, including on a bare IP with no domain.
//   - Let's Encrypt, when the tunnel has a real domain name pointing at it.
//
// The second is worth having for a reason that is not really about encryption:
// the client is our own code and skips verification either way. It is about
// what the connection looks like from outside. Genuine HTTPS on port 443 never
// presents a self-signed certificate, so one is a distinguishing mark on a
// route where being distinguishable is the problem. A real certificate removes
// it, and is also what a CDN in front of the tunnel requires.

type TLSSettings struct {
	CertFile string
	KeyFile  string

	ACMEDomain string
	ACMEEmail  string
	ACMECacheDir string

	FallbackCertFile string
	FallbackKeyFile  string
}

func (s TLSSettings) UsesACME() bool { return s.ACMEDomain != "" }

func ServerTLSConfig(s TLSSettings, logf func(string, ...any)) (*tls.Config, error) {
	var cfg *tls.Config
	var err error
	if s.UsesACME() {
		cfg, err = acmeTLSConfig(s, logf)
	} else {
		cfg, err = fileTLSConfig(s.CertFile, s.KeyFile)
	}
	if err != nil {
		return nil, err
	}
	pinHTTP11ALPN(cfg)
	return cfg, nil
}

func HTTPSConfig(s TLSSettings, logf func(string, ...any)) (*tls.Config, error) {
	if s.UsesACME() {
		return acmeTLSConfig(s, logf)
	}
	return fileTLSConfig(s.CertFile, s.KeyFile)
}

func pinHTTP11ALPN(cfg *tls.Config) {
	protos := []string{"http/1.1"}
	if hasProto(cfg.NextProtos, acme.ALPNProto) {
		protos = append(protos, acme.ALPNProto)
	}
	cfg.NextProtos = protos
}

type certReloader struct {
	certFile string
	keyFile  string

	mu      sync.RWMutex
	cert    *tls.Certificate
	modTime time.Time
}

func fileTLSConfig(certFile, keyFile string) (*tls.Config, error) {
	r := &certReloader{certFile: certFile, keyFile: keyFile}
	if _, err := r.load(); err != nil {
		return nil, err
	}
	return &tls.Config{
		GetCertificate: r.get,
		MinVersion:     tls.VersionTLS12,
	}, nil
}

func (r *certReloader) load() (*tls.Certificate, error) {
	cert, err := tls.LoadX509KeyPair(r.certFile, r.keyFile)
	if err != nil {
		return nil, err
	}
	var mod time.Time
	if st, err := os.Stat(r.certFile); err == nil {
		mod = st.ModTime()
	}

	r.mu.Lock()
	r.cert, r.modTime = &cert, mod
	r.mu.Unlock()
	return &cert, nil
}

func (r *certReloader) get(*tls.ClientHelloInfo) (*tls.Certificate, error) {
	r.mu.RLock()
	cert, known := r.cert, r.modTime
	r.mu.RUnlock()

	if st, err := os.Stat(r.certFile); err == nil && st.ModTime().After(known) {
		if fresh, err := r.load(); err == nil {
			return fresh, nil
		}
	}
	if cert == nil {
		return nil, fmt.Errorf("no certificate loaded")
	}
	return cert, nil
}

func acmeTLSConfig(s TLSSettings, logf func(string, ...any)) (*tls.Config, error) {
	if s.ACMECacheDir == "" {
		return nil, fmt.Errorf("acme cache directory is not set")
	}
	if err := os.MkdirAll(s.ACMECacheDir, 0700); err != nil {
		return nil, fmt.Errorf("acme cache directory: %w", err)
	}

	m := &autocert.Manager{
		Prompt:     autocert.AcceptTOS,
		Cache:      autocert.DirCache(s.ACMECacheDir),
		HostPolicy: autocert.HostWhitelist(s.ACMEDomain),
		Email:      s.ACMEEmail,
	}

	cfg := m.TLSConfig()
	cfg.MinVersion = tls.VersionTLS12

	issue := cfg.GetCertificate
	var fallback *certReloader
	if s.FallbackCertFile != "" && s.FallbackKeyFile != "" {
		fallback = &certReloader{certFile: s.FallbackCertFile, keyFile: s.FallbackKeyFile}
		if _, err := fallback.load(); err != nil {
			logf("the fallback certificate could not be read (%v); "+
				"a failed Let's Encrypt issuance will refuse handshakes", err)
			fallback = nil
		}
	}
	warned := false
	cfg.GetCertificate = func(hello *tls.ClientHelloInfo) (*tls.Certificate, error) {
		want := hello
		if hello.ServerName == "" {
			clone := *hello
			clone.ServerName = s.ACMEDomain
			want = &clone
		}
		crt, err := issue(want)
		if err == nil || fallback == nil {
			return crt, err
		}
		if !warned {
			warned = true
			logf("serving the self-signed certificate because Let's Encrypt has not "+
				"issued one for %s yet (%v) — the browser will warn, and the panel "+
				"switches to the real certificate on its own once issuance succeeds",
				s.ACMEDomain, err)
		}
		return fallback.get(want)
	}
	if !hasProto(cfg.NextProtos, acme.ALPNProto) {
		cfg.NextProtos = append(cfg.NextProtos, acme.ALPNProto)
	}

	acmeResponder.use(m, logf)
	primeACMECert(m, s.ACMEDomain, fallback != nil, logf)

	return cfg, nil
}

const acmePrimeTimeout = 6 * time.Minute

func primeACMECert(m *autocert.Manager, domain string, hasFallback bool, logf func(string, ...any)) {
	fallbackNote := "TLS will not come up until this succeeds."
	if hasFallback {
		fallbackNote = "The self-signed certificate is being served meanwhile, so the " +
			"page still opens — with a browser warning — and switches over on its own once this succeeds."
	}
	if logf == nil {
		logf = func(string, ...any) {}
	}
	go func() {
		done := make(chan error, 1)
		go func() {
			_, err := m.GetCertificate(&tls.ClientHelloInfo{
				ServerName: domain,
				CipherSuites: []uint16{
					tls.TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,
					tls.TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,
				},
				SupportedCurves: []tls.CurveID{tls.CurveP256},
				SignatureSchemes: []tls.SignatureScheme{
					tls.ECDSAWithP256AndSHA256,
					tls.PSSWithSHA256,
				},
				SupportedVersions: []uint16{tls.VersionTLS13, tls.VersionTLS12},
			})
			done <- err
		}()

		select {
		case err := <-done:
			if err != nil {
				logf("certificate for %s could not be obtained: %v — %s "+
					"Check that %s resolves to this server, that port 80 is reachable from outside (or that this "+
					"listener is on 443), and that this server can reach acme-v02.api.letsencrypt.org",
					domain, err, fallbackNote, domain)
				return
			}
			logf("certificate for %s is ready", domain)
		case <-time.After(acmePrimeTimeout):
			logf("certificate for %s did not arrive within %s — still trying on the next connection",
				domain, acmePrimeTimeout)
		}
	}()
}

func hasProto(list []string, want string) bool {
	for _, p := range list {
		if p == want {
			return true
		}
	}
	return false
}
--- END OF FILE ---