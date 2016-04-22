#!/usr/bin/env python

import argparse, ConfigParser, sys, json, os
from redmine import Redmine
from slackclient import SlackClient
from time import sleep
import re

from config import REDMINE_KEY, REDMINE_URL, AUTH_TOKEN

class Bot:
    """This is a super bot"""
    topics = {}
    client = None
    debug = False
    my_user_name = ''

    def connect(self, token):
        self.redmine = Redmine(REDMINE_URL, key=REDMINE_KEY, requests={'verify': False})
        self.client = SlackClient(token)
        self.client.rtm_connect()
        self.my_user_name = self.client.server.username
        print 'Connected to Slack.'

    def listen(self):
        """Listens for messages from slack. endless"""
        while True:
            try:
                some_input = self.client.rtm_read()
                if some_input:
                    for action in some_input:
                        if self.debug:
                            print action
                        if 'type' in action and action['type'] == "message":
                            # Uncomment to only respond to messages addressed to us.
                            # if 'text' in action
                            #     and action['text'].lower().startswith(self.my_user_name):
                            self.process_message(action)
                else:
                    sleep(1)
            except Exception as e:
                print("Exception: ", e.message)

    def process_message(self, message):
        """Magic method"""
        PATTERN = 'issues/(\d{4,5})'

        for topic in self.topics.keys():
            if topic.lower() in message['text'].lower():
                res = re.search(PATTERN, message['text'].lower())
                if res and len(res.groups()):
                    issue = res.groups()[0]
                    message['task'] = issue
                    message['title'] = self.get_issue_title(issue)
                    print 'Issue ', res
                response = self.topics[topic].format(**message)
                if response.startswith('sys:'):
                    response = os.popen(response[4:]).read()
                print "Posting to [%s]: %s" % (message['channel'], response,)
                self.post(message['channel'], response)

    def get_issue_title(self, issue_number):
        """Gets issue subject from redmine server."""
        #project = redmine.project.get('dev-ideas')

        issue = self.redmine.issue.get(issue_number, include='children,journals,watchers')
        return issue.subject

    def post(self, channel, message):
        chan = self.client.server.channels.find(channel)

        if not chan:
            raise Exception("Channel %s not found." % channel)

        return chan.send_message(message)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''
This script posts responses to trigger phrases.
Exec with:
ticket_search.py keys.json
''', epilog='''''' )
    parser.add_argument('-d', action='store_true', help="Print debug output.")
    parser.add_argument('topics_file', type=str, nargs=1,
                        help='JSON of phrases/responses to read.')
    args = parser.parse_args()

    # Create a new Bot
    conv = Bot()

    if args.d:
        conv.debug = True

    conv.connect(AUTH_TOKEN)

    # Add our topics to the Bot
    with open(args.topics_file[0]) as data_file:
        conv.topics = json.load(data_file)

    # Run loop
    conv.listen()
