# Direct layer-3 tunnel

Every other transport in ParsTanel forwards **ports**: a listener on the Iran
server, a backend dial on the kharej server, and a stream in between. This one
is different. It creates a network **interface** on each host and carries whole
IP packets between them, so the two servers get an ordinary point-to-point
link — `10.10.0.1` talking to `10.10.0.2` — over which anything at all can be
routed.

It is the GRE/IPIP idea, built into ParsTanel's own core rather than borrowed
from the kernel, and carried inside ParsTanel's own transports.

### Always GRE + Noise

Every direct tunnel is wrapped the same way: **GRE + Noise**. There is no
choice to make and the wizard does not ask — but the name is worth eight
characters of explanation, because "GRE" on its own means something else.

A kernel GRE tunnel — `ip tunnel add gre1 mode gre`, what most guides mean by
"GRE" — puts its packets on the wire as bare **IP protocol 47**. It is
unencrypted, it is visible for exactly what it is, and it is removed by a single
firewall rule. Kernel IPIP is protocol 4 and no better off.

ParsTanel writes the same GRE header — RFC 2784, with the RFC 2890 key — but the
header is not what travels. It is sealed inside an encrypted session and handed
to a carrier, so what a capture sees is the carrier: an ordinary TCP flow, a UDP
stream, ICMP echo, or forged packets. There is no protocol 47 to block.

Two consequences follow, and the second is the cost:

- Nothing about the tunnel is visible or unencrypted, and no single rule stops
  it.
- **It does not interoperate.** A Cisco, a MikroTik or a plain Linux GRE
  endpoint cannot talk to it. ParsTanel talks to ParsTanel.

There is one encapsulation and it is **GRE**. A config that still says
`encap = "ipip"` is read as GRE, so a tunnel built before the choice was removed
keeps loading — but **both ends must be on the same version**, and the handshake
refuses a mismatch by name if they are not.

Two encapsulations were a way for the two ends to disagree, and the
disagreement cost far more than the choice was worth: ipip saved four bytes,
and a pair that disagreed came up, reported a peer, logged nothing above debug,
and carried nothing at all.

The config value stays `encap = "gre"` — both ends compare it, so it cannot
change. Only what the screens call it changed.

> **Linux only.** It needs `/dev/net/tun` and `CAP_NET_ADMIN` (in practice,
> root). Every other platform reports that plainly and refuses to start.

---

## When you want it

Use the layer-3 tunnel when a port forwarder is the wrong shape:

- You need to carry **protocols that have no ports** — ICMP, OSPF, ESP.
- You want the two servers on **one private network**, reachable by address
  rather than by a mapping written in advance.
- You want to run **routing** across the link.
- You are carrying something that already brings its own reliability and
  encryption, and you only need packets moved.

Use a reverse or direct **port** tunnel for the ordinary case: exposing a few
services on the Iran server. It is simpler, it needs no privileges beyond the
ports themselves, and it is the path with years of production behind it.

## Direction is free

Once the tunnel is up it is symmetric. The only asymmetry is who reaches out
first, and you choose that per deployment:

| | `mode = "dial"` | `mode = "listen"` |
|---|---|---|
| What it does | Reaches out to the peer | Waits to be dialled |
| Needs an open inbound port | No | Yes |

Put `listen` on whichever host can accept an inbound connection, and `dial` on
the other. For the Iran ⇄ kharej case that is normally `dial` on Iran and
`listen` on kharej, which is the **direct** direction — Iran needs no inbound
port of its own.

---

## Setting one up

**From the menu — the easy way.** Run `sudo parstanel`, choose **Setup Iran** or
**Setup Kharej**, then **Direct**, then **Full IP tunnel**. It asks which machine you are on and how the packets
should travel, suggests private addresses for both ends, and writes the config
itself.

The rest of this page is what it writes.

Two files, one on each host. They must agree on the token, the encapsulation
and the carrier.

**Iran** (`/etc/parstanel/l3.toml`):

```toml
[l3]
mode     = "dial"
addr     = "KHAREJ_IP:9000"
token    = "USE_A_LONG_RANDOM_TOKEN"
local_ip = "10.10.0.1/30"
peer_ip  = "10.10.0.2"
```

**Kharej** (`/etc/parstanel/l3.toml`):

```toml
[l3]
mode     = "listen"
addr     = "0.0.0.0:9000"
token    = "USE_A_LONG_RANDOM_TOKEN"
local_ip = "10.10.0.2/30"
peer_ip  = "10.10.0.1"
```

Start both. Each host brings up a `bp0` interface, and from Iran:

```
ping 10.10.0.2
```

From here the two servers are on a private network. Route what you like across
it, expose a service on the tunnel address, or forward ports over it — the link
is an ordinary interface and behaves like one.

---

## Forwarding ports over the tunnel

You can keep the familiar `ports = [...]` interface on top of the layer-3
tunnel. Add it to the Iran side:

```toml
[l3]
mode     = "dial"
addr     = "KHAREJ_IP:9000"
token    = "USE_A_LONG_RANDOM_TOKEN"
local_ip = "10.10.0.1/30"
peer_ip  = "10.10.0.2"

ports      = ["443", "2053-2060", "8080=80"]
accept_udp = true
```

Port 443 on Iran now reaches port 443 on kharej, across the tunnel. The syntax
is the reverse tunnel's, so a config moves across unchanged:

| Mapping | Effect |
|---|---|
| `443` | `:443` → `peer:443` |
| `443=8443` | `:443` → `peer:8443` |
| `443=10.0.0.5:8443` | `:443` → an explicit host |
| `127.0.0.1:443=8443` | bind to one local address only |
| `10000-10009` | a range, each to the same port |
| `10000-10009=20000-20009` | a range, preserving the offset |
| `443=10.0.0.1:80\|10.0.0.2:80` | two backends, load-balanced |

A target with no host of its own means `peer_ip`, which is what almost every
mapping wants. `accept_udp` adds UDP alongside TCP; it is off by default, for
the same reason it is on the reverse tunnel — a web tunnel should not silently
start carrying every QUIC flow on port 443.

**Ports are optional.** Leave them out and the tunnel simply carries whatever
the kernel routes into the interface, which is the plain layer-3 case.

Two things worth knowing:

- **The forwarder outlives tunnel restarts.** Listeners are opened once. If the
  engine rebuilds its session, connections already open are undisturbed, and
  while the tunnel is genuinely down new connections are refused rather than
  left hanging.
- **This is ordinary userspace forwarding.** For the highest possible
  throughput you can skip it and use kernel `iptables` DNAT over `bp0` instead
  — the interface is a normal one and nothing here prevents it.

---

## Options

| Key | Default | What it does |
|---|---|---|
| `mode` | *required* | `dial` or `listen`. Its absence is what tells ParsTanel there is no layer-3 tunnel here at all |
| `addr` | *required* | Peer `host:port` when dialling; bind address when listening |
| `token` | *required* | The shared secret. The only credential |
| `local_ip` | *required* | This end's tunnel address, normally with a prefix: `10.10.0.1/30` |
| `peer_ip` | | The other end's tunnel address. Required if `local_ip` has no prefix |
| `encap` | `gre` | `gre` — a file that says `ipip` is read as GRE |
| `gre_key` | `0` | RFC 2890 key, letting several logical tunnels share a carrier. `gre` only |
| `carrier` | `udp` | `udp`, `quic`, `pck`, `sni`, `xdi` or `spoof` — see below |
| `iface` | `bp0` | Interface name to create |
| `mtu` | `1400` | Interface MTU |
| `sockbuf` | 4 MiB | Carrier socket buffers |
| `fec_data` | `0` | Error correction: data packets per group. Both keys or neither — see [Error correction](#error-correction) |
| `fec_parity` | `0` | Error correction: spare packets per group |
| `paths` | `1` | Spread the `udp` carrier over this many sockets — see [Several sockets](#several-sockets) |
| `sni_domain` | built-in | The domain the `sni` carrier announces. `sni` only |
| `ports` | none | Forwarded port mappings — see above |
| `accept_udp` | `false` | Forward UDP as well as TCP on those ports |

### Carriers

Plain UDP is right on a path that does not interfere. On one that does, it is
the first thing to go — a long-lived UDP flow to a foreign address is among the
easiest patterns to rate-limit. The other three carry the same encrypted
packets somewhere less obvious:

| `carrier` | What is on the wire | Overhead | Needs |
|---|---|---|---|
| `udp` | UDP datagrams | 28 | nothing |
| `quic` | a real QUIC session, carrying the tunnel in RFC 9221 datagrams | 60 | nothing |
| `pck` | TCP segments built without a socket — no handshake, no connection state | 52 | root / `CAP_NET_RAW` |
| `sni` | `pck`, plus a TLS hello naming an allowed domain at the start of the flow | 52 | root / `CAP_NET_RAW` |
| `xdi` | ICMP echo, for a path that filters UDP and TCP but not ping | 33 | root / `CAP_NET_RAW` |
| `spoof` | raw IP with a forged source address | 28+ | root / `CAP_NET_RAW` |

The obfuscated ones are **Linux only**. `pck`, `xdi` and `spoof` are the same
carriers those transports already use — the layer-3 tunnel simply hands them its
own packets instead of KCP's, so a fix to a carrier reaches both at once.

`quic` is not imitating anything: it opens a real QUIC connection, with a real
TLS 1.3 handshake and `h3` as the ALPN, and puts the tunnel in QUIC's unreliable
DATAGRAM frames. To a path it is the HTTP/3 that dominates a modern network. It
is the only obfuscated choice that needs no root. The certificate it presents is
for the shape and not for the secrecy — the tunnel's own payload is sealed by
Noise before it reaches any carrier, and the peer is authenticated by the token.

`sni` is `pck` with one extra segment at the start of the flow: a TLS
ClientHello naming a domain the path is known to allow. A box that classifies by
server name reads it, decides the flow is permitted, and stops looking; the
tunnel's segments follow on the same five-tuple. Set `sni_domain` to a name your
own route already reaches. The far end drops the hello before the tunnel sees it.
The technique is patterniha's, by way of therealaleph/sni-spoofing-rust.

### Error correction

A layer-3 tunnel may not ride on anything that retransmits — see [why](#limits)
— but it can carry **redundancy**. For every `fec_data` packets the tunnel
sends, it sends `fec_parity` spare ones, and any `fec_parity` of the group may
be lost without losing anything: the far end rebuilds them, with nothing waiting
for a timer.

It is for a path that drops packets **steadily** — a congested international
route, a lossy last mile. Measured against a link dropping 20%, an application
saw **3.5% loss with it on and 39% with it off**, for about a third more
traffic. On a clean route that third is pure waste, so it is off by default.

```toml
[l3]
carrier    = "spoof"
fec_data   = 10
fec_parity = 3
```

- **Both ends must set the same pair.** It is not negotiated; a receiver
  expecting a different scheme rebuilds nothing.
- It works over **every** carrier — `udp`, `quic`, `spoof`, `pck`, `sni`, `xdi`.
- Half a scheme is refused at startup: set both keys, or neither.
- The recommended pair (10/3) is what the wizard's *Turn on error correction*
  and the panel's checkbox write.

### Several sockets

A tunnel on one UDP socket is one flow, and some providers give **each flow its
own speed limit** — so the tunnel sits at one flow's allowance however fast the
link really is. `paths` spreads the same traffic over several sockets, which is
several flows, which is several allowances.

```toml
[l3]
carrier = "udp"
paths   = 4
```

- The sockets use **consecutive ports** counting up from the tunnel port — `paths = 4`
  on port 9000 uses 9000–9003, and those must be open on the listening side.
- **Both ends must set the same number.**
- It is for the **`udp` carrier only**. ParsTanel refuses `paths` on the obfuscated
  carriers because they already vary their source per packet.
- Nothing is added to the wire — the MTU is unchanged.

```toml
[l3]
mode          = "dial"
addr          = "KHAREJ_IP:9000"
token         = "USE_A_LONG_RANDOM_TOKEN"
carrier       = "pck"
local_ip      = "10.10.0.1/30"
peer_ip       = "10.10.0.2"
mtu           = 1380
pck_interface = "eth0"
```

> **`spoof` listeners need `spoof_peer_ip`.** ParsTanel refuses the config up
> front if it is missing, because the peer forges the source of every packet.

### Encapsulation

**GRE**, always. Four bytes, or eight when a key is set.
It carries IPv4 and IPv6 over the same tunnel.

### MTU

The default of **1400** is deliberately low. The budget is:

```
mtu = path − outer IP − carrier − session (29) − encap
```

On a clean 1500-byte path with `udp` that comes to **1439** (GRE's four bytes
included).

---

## Security

The handshake is **Noise NNpsk0** with the pre-shared key derived from your
token, giving an encrypted, mutually authenticated, forward-secret channel. On
top of that:

- Every packet carries an **explicit counter** and is checked against a
  2048-bit **sliding replay window**.
- The header is **authenticated** as additional data.
- Sessions **rekey** every two minutes.
- A peer without the token gets **no reply at all**.
- The peer's address is only ever learned from a packet that has already
  authenticated.

All of the above is ParsTanel's, and it is why the kernel's own tunnels are
not used here.

---

## Limits

- **Linux only**, and needs root or `CAP_NET_ADMIN`.
- **No reliable carrier, ever.** `tcp`, `ws` and `kcp` are refused by design:
  stacking two retransmit timers makes throughput collapse under loss rather
  than degrade (TCP-over-TCP meltdown).
- **Two peers**, not many.

## It cannot disturb a reverse tunnel

The layer-3 tunnel lives in its own `[l3]` table and its own package. A
configuration file that does not mention `[l3]` cannot reach any of this code,
and one that does never reaches the reverse engine.

## TCP segment cap (MSS clamp)

### The fault

The tunnel's MTU is smaller than 1500 bytes. A TCP connection crossing the
tunnel negotiates a segment size from its own interfaces and sends packets that
cannot fit. Many networks drop the ICMP "fragmentation needed" message, so
downloads stall while ping and SSH work fine.

### The fix

ParsTanel rewrites the MSS option in the SYN of each TCP connection leaving the
tunnel interface:

| `mss_clamp` | Meaning |
|---|---|
| `0` | automatic — the MTU minus 40 (IPv4) or 60 (IPv6). The default. |
| a number | that value exactly |
| `-1` | off |

### Checking it

```bash
iptables -t mangle -S | grep parstanel-l3-mss
```

Every rule ParsTanel installs is now deleted until the delete fails before a new
one is added, so a process that was killed leaves nothing behind.

## Automatic MTU

On by default. The tunnel measures what the path really carries and sets the
interface to match, instead of trusting the number in the file.

### How it works

Each end sends probe packets padded to the size a full data packet would be,
and binary-searches for the largest that comes back acknowledged.
Probes are encrypted under the tunnel session and re-measured every 30 minutes.

### Turning it off

```toml
[l3]
auto_mtu = false
```

---

<div dir="rtl">

## خلاصهٔ فارسی

تونل مستقیم **لایه ۳ (Full IP Tunnel)** یک شبکهٔ خصوصی واقعی بین دو سرور می‌سازد
(مثل `10.10.0.1` و `10.10.0.2`) و تمام ترافیک IP را جابه‌جا می‌کند، نه فقط پکت‌های
یک پورت خاص را.

کپسوله‌سازی همیشه **GRE + Noise** است که ترافیک را امن و ضدشنود می‌کند. حامل‌ها
(Carriers) می‌توانند UDP ساده، QUIC، PCK، SNI spoofing یا IP spoofing باشند.
این روش نیازمند لینوکس و دسترسی root است.
قابلیت تصحیح خطا (FEC) و تقسیم روی چند سوکت (Multipath) هم در این مد فعال است.

</div>