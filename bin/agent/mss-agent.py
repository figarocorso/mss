#!/usr/bin/python
# -*- coding: UTF-8 -*-

import sys
import os
from SimpleXMLRPCServer import SimpleXMLRPCServer
from mss.agent.module import ModuleManager
from mss.agent.process import ExecManager
from mss.agent.translation import TranslationManager
from mss.agent.daemon import Daemon
from mss.agent.auth import authenticate

class MSS(Daemon):
    def run(self):
        EM = ExecManager()
        TM = TranslationManager()
        MM = ModuleManager(EM, TM)
        server = SimpleXMLRPCServer(("localhost", 8001), allow_none=True,
            logRequests=False)
        server.register_instance(MM)
        server.register_function(authenticate)
        server.serve_forever()

if __name__ == "__main__":
    daemon = MSS('/var/run/mss-agent.pid')
    if len(sys.argv) == 2:
        if 'start' == sys.argv[1]:
            daemon.start()
        elif 'stop' == sys.argv[1]:
            daemon.stop()
        elif 'restart' == sys.argv[1]:
            daemon.restart()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "Usage: %s start|stop|restart" % sys.argv[0]
        sys.exit(2)
