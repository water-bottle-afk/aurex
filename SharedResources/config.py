__author__ = "Nadav"

# ── Network addresses ─────────────────────────────────────────────────────────
SERVER_IP,  SERVER_PORT  = "10.100.102.58", 55554   # marketplace server
GATEWAY_IP, GATEWAY_PORT = "10.100.102.58", 14444   # gateway (unused direct port)

GATEWAY_BLOCKCHAIN_PORT  = 33334   # nodes connect here to reach the gateway
SERVER_PORT_FOR_GATEWAY  = 23456   # legacy; gateway uses SERVER_PORT now
GATEWAY_UDP_PORT         = 22222   # UDP broadcast port for gateway discovery
BLOCKCHAIN_NODE_IP       = "10.100.102.58" #default IP for blockchain nodes to bind to (can be overridden with --ip)

BROADCAST_DISCOVERY_FREQUENCY = 3   # seconds between UDP discovery retries
POW_DIFFICULTY   = 3                 
INITIAL_BALANCE  = 100               