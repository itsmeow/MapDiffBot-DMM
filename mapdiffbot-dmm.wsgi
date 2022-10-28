#!/usr/bin/python
# This should go in a directory ABOVE the folder containing the repo
import sys
import logging
logging.basicConfig(stream=sys.stderr)
# Change this to the path containing this file
sys.path.insert(0, "/srv/mdb")
# MapDiffBot-DMM should be the name of the folder containing the repo's files
import importlib
application = importlib.import_module("MapDiffBot-DMM.server").app