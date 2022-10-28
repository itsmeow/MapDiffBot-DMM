#!/usr/bin/python
# This should go in a directory ABOVE the folder containing the repo
import sys
import logging
logging.basicConfig(stream=sys.stderr)
# Change this to the path containing this file
sys.path.insert(0, "/srv/mdb")
# The folder with the repo in it should be named mapdiffbotdmm
from mapdiffbotdmm.server import app as application