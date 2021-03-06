#!/usr/bin/python
# coding: utf-8
#
# Copyright (C) 2012 André Panisson
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''
This script starts an HTTP server that connects to the Twitter Streaming API and 
shows the Twitter data in Graph Streaming format,
with the users as nodes and retweets as edges.

You have to install the tweepy client (http://joshthecoder.github.com/tweepy/)
in order to run this script.

To connect to the server with Gephi, you must install Gephi with 
the Graph Streaming plugin.
1. Start Gephi
2. Go to the tab Streaming,right-click on Client and click on "Connect to Stream"
3. Enter the Source URL http://localhost:8181/?q=twitter (or other keywords if the 
    server is filtering other keywords) and click OK

The nodes and edges start to appear in the graph visualization. You can run
the Force Atlas layout in order to get a better layout.

Usage: server.py [options]

Options:
  -h, --help            show this help message and exit
  -u USER, --user=USER  Twitter username to connect
  -p PASSWORD, --password=PASSWORD
                        Twitter password to connect
  -q QUERY, --query=QUERY
                        Comma-separated list of keywords
  -l LOG, --log=LOG     Output log of streaming data


Created on Nov 10, 2010

@author: panisson
'''
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn
import urlparse
import tweepy
import re
from pygephi import GephiFileHandler
import threading
import Queue
import socket
import optparse
import sys
import time

api = tweepy.API()
active_queues = []

class Status(object):
    
    def __init__(self, status_id, source, target, text, date):
        self.status_id = status_id
        self.source = source
        self.target = target
        self.text = text
        self.date = date

class StreamingListener(tweepy.StreamListener):
    
    def __init__(self, *args, **kwargs):
        tweepy.StreamListener.__init__(self, *args, **kwargs)
        self.known_users = {}
        self.stream_log = None
    
    def on_data(self, data):
        self.stream_log.write(data)
        self.stream_log.flush()
        super(StreamingListener, self).on_data(data)
    
    def on_status(self, status):
        print status.text
        
        m = re.search('(?<=RT\s@)\w+', status.text)
        if m:
            source_user = m.group(0).lower()
            target_user = status.user.screen_name
            status_id = status.id
            date = status.created_at
            text = status.text
            
            dispatch_event(Status(status_id, source_user, target_user, text, date))
            
def dispatch_event(e):
    for q in active_queues:
        q.put(e)
        
class RequestProcessor():
    
    def __init__(self, parameters, out):
        
        self.known_users = {}
        
        if "q" in parameters:
            q = parameters["q"][0]
            self.terms = q.split(",")
            print "Request for retweets, query '%s'"%q
        else:
            self.terms = None
            print "Request for retweets, no query string"
        
        self.handler = GephiFileHandler(out)
    
    def process(self, status):
        messages = []
        
        found = False
        if (self.terms):
            for term in self.terms:
                if re.search(term, status.text.lower()):
                    found = True
                    break
            if not found:
                return messages
            
        default_node_attr = {'size':5, 'r':84./255., 'g':148./255., 'b':183./255.}
            
        if status.source not in self.known_users:
            self.known_users[status.source] = status.source
            attributes = default_node_attr.copy()
            attributes['label'] = status.source
            self.handler.add_node(status.source, **attributes)
            
        if status.target not in self.known_users:
            self.known_users[status.target] = status.target
            attributes = default_node_attr.copy()
            attributes['label'] = status.target
            self.handler.add_node(status.target, **attributes)
        
        attributes = {'directed':True, 'weight':2.0, 'date':str(status.date)}
        self.handler.add_edge(status.status_id, status.source, status.target, **attributes)

class RequestHandler(BaseHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        BaseHTTPRequestHandler.__init__(self, *args, **kwargs)
        
    def do_POST(self):
        pass

    def do_GET(self):
        
        param_str = urlparse.urlparse(self.path).query
        parameters = urlparse.parse_qs(param_str, keep_blank_values=False)
        
        self.queue = Queue.Queue()
        active_queues.append(self.queue)
        
        self.wfile.write('\r\n')
        
        request_processor = RequestProcessor(parameters, self.wfile)
        
        while True:
                        
            status = self.queue.get()
            if status is None: break
            
            try:
                
                request_processor.process(status)
                
            except socket.error:
                print "Connection closed"
                active_queues.remove(self.queue)
                return
        
class Collector(threading.Thread):
    def __init__(self, options):
        self.options = options
        threading.Thread.__init__(self)
        
    def run(self):
        q = self.options.query.split(",")
#        q = [e+ ' rt' for e in q]
        
        print "Streaming retweets for query '%s'"%q
        listener = StreamingListener()
        
        def on_error(status_code):
            if status_code == 401:
                raise Exception("Authentication error")
        listener.on_error = on_error
        
        listener.stream_log = file(self.options.log, 'a')
        auth = tweepy.BasicAuthHandler(self.options.user, self.options.password)
        stream = tweepy.streaming.Stream(auth, listener, timeout=60.0)
        while (True):
            try:
                stream.filter(track=q)
            except socket.gaierror:
                print "Stream closed"
                time.sleep(60)
            except Exception, e:
                print str(e)
                time.sleep(60)
        
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    
    def start(self):
        self.serve_forever()
        
    def stop(self):
        self.socket.close()
        
def parseOptions():
    parser = optparse.OptionParser()
    parser.add_option("-u", "--user", type="string", dest="user", help="Twitter username to connect", default='undefined')
    parser.add_option("-p", "--password", type="string", dest="password", help="Twitter password to connect", default='undefined')
    parser.add_option("-q", "--query", type="string", dest="query", help="Comma-separated list of keywords", default="twitter")
    parser.add_option("-l", "--log", type="string", dest="log", help="Output log of streaming data", default="/tmp/stream.log")
    parser.add_option("-s", "--serverport", type="int", dest="serverport", help="HTTP server port", default=8181)
    (options, _) = parser.parse_args()
    if options.user == 'undefined':
        parser.error("Twitter username is mandatory")
    if options.password == 'undefined':
        options.password = raw_input("Password for Twitter user '%s': "%options.user)
    return options
        
def main():
    options = parseOptions()
    collector = Collector(options)
    collector.setDaemon(True)
    collector.start()
    try:
        server = ThreadedHTTPServer(('', options.serverport), RequestHandler)
        print 'Test server running...'
        server.start()
    except KeyboardInterrupt:
        print 'Stopping server...'
        server.stop()
        dispatch_event(None)
        sys.exit(0)

if __name__ == '__main__':
    main()