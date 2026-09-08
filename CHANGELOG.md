# Changelog

All notable changes to ParsTanel are documented here.

## v1.7.7.5 — 2026-09-07

Managed servers are reached over SSH now, and the panel that drives them is the
only panel. Those are the same change told twice. The old node model was an
agent ParsTanel installed on the far server, listening on a port of its own,
speaking a protocol of its own — and it was the reason adding a server took
minutes, reported three tunnels where there was one, and built tunnels that did
not carry traffic. What it was really doing was reimplementing, badly, something
every one of these servers already runs. So it is gone: a server is added with
an address, a port, a username and a password, and ParsTanel logs in the way you
would. There is no agent, no port to open, and nothing to install before the
first connection.

The rebuilt panel replaces the classic one rather than sitting beside it. It was
served at /panel/ behind a per-server setting for as long as it was unfinished,
with an escape hatch back to the single-file dashboard; that scaffolding, and
the 350 KB dashboard it protected, are both removed. The panel answers at "/".

The rest is what a week of using it turned up. Every figure the overview showed
was formatted before it was totalled, so the totals were wrong in a way no
screenshot could reveal. The open-file-limit health check measured the wrong
process and advised a fix that could not work. The speed test blamed the far
server for a connection this one refused. A layer-3 tunnel whose far side had
nothing listening on the mapped port said nothing at all about it. None of these
announce themselves; each was found by running the thing and reading what it
claimed against what was true.

### Changed

- **Managed servers speak SSH.** Adding one asks for the four things an SSH
  login needs — address, port (22 unless yours differs), username (usually
  root) and password — and the host key is trusted on first use and pinned
  after. ParsTanel installs itself on the far server over that connection,
  reports its version, system and uptime on the server card, and upgrades it
  from the panel with one click when a release lands. **The node agent, its
  listening port and its wire protocol are removed**; a server enrolled the old
  way must be added again.

- **The panel is served at "/".** /panel/ redirects there, so a bookmark, a
  pinned tab or a link somebody was sent keeps working. The Interface setting
  that chose between the two panels, the /api/panelui endpoint behind it and the
  ?panel=classic escape hatch are gone with the panel they switched to.

- **Reverse tunnels are built through managed servers only.** The panel used to
  offer "I will set the other one up myself" and a setup link to paste on the
  far server; both are removed. A tunnel to a server that is not in the fleet is
  made from the CLI menu, and the panel shows its card like any other.

- **IP spoofing and SNI spoofing are CLI-only.** They stay available from the
  menu and stay fully supported; what they no longer have is a place in the
  panel's Add tunnel, where they were the two carriers most likely to be picked
  without understanding what they do to a route.

### Fixed

- **The panel's Logs never opened.** Every Logs button answered "404 page not
  found", on both ends of every tunnel, and the viewer sat on "Reading" for a
  request that had already failed — which is also why logs looked stale, why
  switching to another server showed nothing, and why what had been on screen
  disappeared. One cause: the logs call built its own URL and asked for it at
  the root of the origin, which is the one address the panel does not answer.

- **"too many segments" was explained wrongly, and confidently.** The log
  explainer matched the phrase and nothing else, so it told an operator on
  1.7.7.5 to "update to 1.7.5 or later" — install something older than what they
  were running — and reported a failing layer-3 read on a TCP reverse tunnel,
  which has no layer-3 read. An explanation now has to say what must be true of
  the tunnel and the version before it is offered, and when nothing fits, the
  panel says nothing.

- **The Add form did not send the preset it was showing.** One button carries
  `on` in the markup, so the form opens with Balance visibly chosen — but the
  choice was only recorded when somebody pressed one. Accepting what was on
  screen wrote a tunnel with no preset at all, and the edit dialog then read an
  empty value and fell back to whichever option the preview was drawn with. The
  two screens disagreed about a tunnel and neither was wrong: nothing had been
  recorded either way.

- **Close did nothing on Alerts, Health check and Speed test.** The preview
  called its close function `cl`, the binding only recognised names beginning
  "close", and so the cross in the header worked while the button actually
  labelled Close did not.

- **The Servers page threw "behind is not defined" on Refresh.** A call left
  behind when the banner it painted was removed.

- **Country and location were blank on every tunnel card.** They came from a
  lookup against providers an Iran server cannot reach, so it returned nothing
  and the card showed a dot where a flag belongs and a dash where a location
  belongs. A managed server is outside that route by definition and answers for
  itself now; failing that, the card shows the address rather than a dash.

- **A server card showed what a machine is, never what it is doing.** What it
  reported was written down when it was added and rewritten only on an upgrade
  or a manual refresh, so version and uptime were frozen at that moment. The
  fleet page asks again when what it holds is more than a few seconds old.

- **The metrics screen ran its headline figures to the edge.** Carrying now,
  Peak in the day and Up last 24 hours sat directly in the dialog body with no
  gutter, while every heading, chart and table around them was inset.

### Added

- **Real-time processor and memory on each server card.** Read on that machine
  when the panel asks — nothing here can see another server's processor — and
  coloured at 75% and 90%.

- **The link test runs on the server that can take it.** It measures the path a
  tunnel dials out over, and only the dialling end has one; an Iran panel holds
  the listening half of every reverse tunnel, so it refused — while holding a
  root shell on the machine that could have answered. When the tunnel is linked
  to a managed server, the panel asks that server and labels the reading with
  where it was taken.

- **Editing a server happens inside its own card.** It used to insert a separate
  form after the card, and another one on every press of Edit, so a server could
  end up with several open forms disagreeing about its address. It is one panel
  per server, on the same surface as the remove confirmation beside it.

- **Every traffic figure on the overview was computed from a formatted string.**
  "1.2 TB" parsed back as 1.2, so totals across tunnels were arithmetic on
  numbers that had lost their units — the all-time traffic, the per-tunnel
  shares and the split between directions were all wrong together, and
  consistently wrong, which is why they looked right. The API sends the raw byte
  counts beside the formatted ones now, and the panel computes with those.

- **The open-file-limit health check measured the panel, not the tunnels.** It
  read the limit of whichever process happened to answer, reported 1024, and
  told the operator to run Optimize and reboot — which changed nothing, because
  the tunnel services carried no LimitNOFILE at all. It reads the limit of the
  tunnel's own process now, and the unit files set one.

- **The speed test blamed the far server for a local refusal.** A connection
  this machine refused was reported as the other end needing its receiver turned
  on, sending operators to a server that was working. A locally refused
  connection is now named as one.

- **A layer-3 tunnel whose far side has nothing listening now says so.** Every
  signal an operator can see said the tunnel was healthy — a session on both
  ends, a completed MTU probe, clean pings, rekeys on schedule — and all of it
  was true; the service behind the forwarded port simply was not there. That
  failure was logged at debug, so the log was silent about the one thing that
  was wrong. It is a warning now, repeated at most once a minute, and the
  recovery is reported too.

- **A pck listener could not start without a default route.** The listening side
  has no peer to route toward, so it probed 1.1.1.1 to find its egress
  interface, and a machine using policy routing, an IPv6-only default or a
  private segment failed with an error naming an address the operator had never
  configured. The listener falls back to the first usable interface; the dialling
  side, which does have a real peer to reach, is unchanged.

- **Enrolling a server could no longer half-finish.** A shutdown or a dropped
  network during enrolment could leave the far server holding credentials this
  one had discarded, unreachable from either side. Enrolment is claimed,
  acknowledged and given a grace period, and a shutdown waits for it rather than
  cutting it short.

- **A tunnel could be held down by a peer that stopped reading, until somebody
  restarted it by hand.** The server writes one byte at a time on its control
  channel — a heartbeat, a request for a pool connection — and those writes had
  no bound. A write lands in the kernel's send buffer and returns; when the path
  to the client goes and the buffer fills, it blocks until the kernel stops
  retransmitting, which is around fifteen minutes on Linux defaults. For that
  whole window the server still believed it had a control channel, so it refused
  every attempt by the client to establish a new one ("a control channel is
  already established"), could not ask for pool connections because the request
  reached nobody, and dropped every user connection with the queue full —
  thousands of lines a second. Nothing it could do would recover it. Control
  writes are bounded at ten seconds now, on all seven transports: past that the
  channel is treated as gone, the transport restarts, and the client's next
  claim is accepted.

- **"the queue is full, dropping a client from ..." named the wrong machine.**
  It printed the local address of the accepted connection, so every one of those
  lines carried the server's own address and the forwarded port — which reads as
  the server connecting to itself, and sends anyone debugging it in the opposite
  direction from the problem. It names the client now.

- **A failed control write reported itself as a read.** "failed to read message
  from net.Conn: write tcp ...: write: connection timed out" was the wire
  helper's error text on the write path.

- **The "Random" button no longer offered a random forwarded port.** It sat
  beside Forwarded ports as well as Tunnel port, and asks the server for a port
  that is free *on this machine* — right for the port this side binds, and the
  opposite of right for a forwarded one, which the field's own hint says goes to
  the same port on the kharej machine. A port chosen for being free here is by
  construction one nothing is listening on there, so the button could only build
  a tunnel that comes up, reports a peer, shows green and refuses every
  connection at the last hop. It is offered for the tunnel port alone, and bound
  to that field rather than to every button carrying the label.

- **A tunnel delivering into nothing no longer reads as healthy.** When the
  service on the far machine is not listening, every connection crosses a
  working tunnel and dies one hop past the end of it — and every reading the
  panel had said so: control channel up, peer connected, counters moving, all
  true. The client records the failing last hop in its metrics snapshot now
  instead of only logging it, the far end reports it to the panel over the same
  SSH connection the fleet already uses, and the card says which address is not
  answering and how many connections have been lost since. The state stays
  "online", because the tunnel is: restarting it would fix nothing, and the
  watchdog reads that field.

- **A server already running an older ParsTanel is upgraded, not refused.**
  Adding one reached it, found a ParsTanel that did not understand the panel's
  command, and reported it as a server that could not be reached — printing the
  far machine's own help into the add form, which told the operator to run
  `parstanel node setup`, the flow this release removes. Every server in an
  existing fleet is in that state the day the panel is upgraded, so this was the
  ordinary path rather than an edge. A binary that is too old is now recognised
  as one to install over, the same as one that is missing, and the install is
  what upgrades it. The panel no longer repeats whatever the far machine
  printed.

- **Creating a tunnel with an unknown preset is refused by name.** It used to be
  accepted and silently ignored, so the tunnel was built on defaults nobody
  chose.

- **Closing a dialog returns to the screen it was opened from.** Every dialog
  drew the tunnels list underneath it, so closing one opened from the overview
  left you somewhere you had not been.

### Added

- **Every redirect the panel sends lands inside the panel.** Handlers below the
  base-path wrapper see the path with the prefix already removed, so a Location
  built from one — `/login`, `/` — pointed at the root of the origin, which is
  now the one place the panel does not answer. Opening the panel bounced to a
  404 and there was no way in at all. Signing in, signing out and the old
  `/panel/` address all carry the prefix now.

- **A four-part version is compared on all four parts.** Versions were read as
  three numbers, so `1.7.7.5` parsed as `[1 7 7]` — the fourth component fell
  inside the last split and was dropped — and was therefore indistinguishable
  from `1.7.7`. Nothing could see a point release as an update: not the CLI's
  check, not the panel's banner, and not the **Upgrade to** button on a managed
  server's card, because all three ask the same function.

- **Update from a file you downloaded yourself.** The download is the step most
  likely to fail on the networks this project exists for — the mirrors help and
  do not always work. **Update → Install from a downloaded file** takes the
  release archive from `/root` instead: fetch
  `parstanel_linux_<arch>.tar.gz` from the releases page on any machine that can
  reach GitHub, `scp` it over, and choose it. The menu line says what it found,
  including the version, which is read by running the binary inside the archive
  rather than guessed from the filename.

- **A tunnel that already exists can be linked to the server holding its other
  end.** Everything the fleet does for a tunnel is gated on a record of
  where that other half lives. The tunnel's own menu links it now, and unlinks it again.

### Security

- **The panel is served under an unguessable path, and answers nowhere else.**
  It now lives under a random 14-character segment.
- **golang.org/x/crypto updated to v0.56.0**, which closes the SSH
  source-address advisory.
