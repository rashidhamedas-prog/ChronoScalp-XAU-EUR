//+------------------------------------------------------------------+
//| chronoscalp_bridge.mq5 — ChronoScalp Professional Edition        |
//| Phase 3 skeleton. Compile in MetaEditor on Windows VPS.          |
//| Listens on 127.0.0.1 for JSON envelopes (see bridge/protocol.py).|
//| EA NEVER opens positions without an authenticated OPEN from      |
//| Python. Heartbeat loss >10s raises BRIDGE_DEGRADED.              |
//+------------------------------------------------------------------+
#property copyright "ChronoScalp"
#property version   "1.00"
#property strict

input string BridgeToken = "";          // Must match Python bridge token
input int    BridgePort  = 18999;
input int    HeartbeatSec = 10;

// Skeleton only — full socket loop is filled during Windows packaging.
int OnInit()
  {
   if(StringLen(BridgeToken) < 8)
     {
      Print("ChronoScalp bridge: token missing — fail closed");
      return(INIT_FAILED);
     }
   Print("ChronoScalp bridge skeleton ready on port ", BridgePort);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) {}

void OnTick()
  {
   // Heartbeat / POSITION_UPDATE / FILL handlers land in Phase 3 packaging.
  }
