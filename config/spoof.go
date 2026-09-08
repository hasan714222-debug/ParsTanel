package config

// Spoof-carrier mode resolution, kept in one place so every consumer agrees
// on configuration structures.
//
// The direct tunnel carries a whole private network over the spoof carrier:
// an inner transport that brings its own reliability (such as WireGuard)
// is routed over the tunnel rather than piped through it.