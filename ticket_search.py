#!/usr/bin/env python

import argparse
import json
import os
from redmine import Redmine
from slackclient import SlackClient
from time import sleep
import re

from config import REDMINE_KEY, REDMINE_URL, AUTH_TOKEN, REDMINE_USERS


class Bot:
    """This is a super bot"""
    topics = {}
    client = None
    debug = False
    my_user_name = ''

    RE_HELP = re.compile(r'^help$')
    RE_ISSUE_INFO = re.compile(r'^issue (?P<issue_id>\d{3,5})$')
    RE_ISSUE_SET_STATUS = re.compile(r'^issue (?P<issue_id>\d{3,5}) status (?P<status_name>.*)$')
    RE_ISSUE_ASSIGN = re.compile(r'^issue (?P<issue_id>\d{3,5}) assign (?P<user_name>.*)$')

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
                if self.debug:
                    raise
                print("Exception: ", e.message)

    def get_issue_repr(self, issue):
        print issue, 'asd'
        return "*{id}*: _{subject}_ *{status}* {assignee}".format(
            id=issue.id,
            subject=issue.subject,
            status=issue.status,
            assignee=('(assigned to %s)' % issue.assigned_to) if hasattr(issue, 'assigned_to') else '(unassigned)'
        )

    def process_message_help(self):
        return '\n'.join([
            '*help* - show help',
            '*issue <issue_id>* - show issue info',
            '*issue <issue_id> assign <user_name>* - change issue assignee',
            '*issue <issue_id> status <status>* - change issue status',
        ])

    def process_message_issue_info(self, issue_id):
        issue = self.redmine.issue.get(issue_id, include='children')
        child_ids = [child.id for child in issue.children]
        children = [self.redmine.issue.get(child_id) for child_id in child_ids]
        return "{info}{children}".format(
            info=self.get_issue_repr(issue),
            children=(''.join(['\n    > %s' % self.get_issue_repr(i) for i in children])) if children else '',
        )

    def process_message_issue_set_status(self, issue_id, status_name):
        issue = self.redmine.issue.get(issue_id)
        statuses = self.redmine.issue_status.all()

        set_status_id = None
        for status in statuses:
            if status.name.lower() == status_name.lower():
                set_status_id = status.id

        if set_status_id is None:
            return 'Unknown status, possible: %s' % ', '.join([i.name for i in statuses])

        issue.status_id = set_status_id
        issue.save()

        issue = self.redmine.issue.get(issue_id)
        return self.get_issue_repr(issue)

    def process_message_issue_assign(self, issue_id, user_name):
        issue = self.redmine.issue.get(issue_id)
        users = REDMINE_USERS

        if user_name.lower() not in users:
            return 'Unknown user, possible: %s' % ', '.join([i.capitalize() for i in users.keys()])

        set_assigned_to_id = users[user_name.lower()]
        issue.assigned_to_id = set_assigned_to_id
        issue.save()

        issue = self.redmine.issue.get(issue_id)
        return self.get_issue_repr(issue)

    def process_message(self, message):
        """Magic method"""
        PATTERN = 'issues/(\d{4,5})'

        text = message['text'].lower()
        print text

        m = self.RE_HELP.match(text)
        if m:
            response = self.process_message_help()
            return self.post(message['channel'], response)

        m = self.RE_ISSUE_INFO.match(text)
        if m:
            response = self.process_message_issue_info(m.group('issue_id'))
            return self.post(message['channel'], response)

        m = self.RE_ISSUE_SET_STATUS.match(text)
        if m:
            response = self.process_message_issue_set_status(m.group('issue_id'), m.group('status_name'))
            return self.post(message['channel'], response)

        m = self.RE_ISSUE_ASSIGN.match(text)
        if m:
            response = self.process_message_issue_assign(m.group('issue_id'), m.group('user_name'))
            return self.post(message['channel'], response)

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
        # project = redmine.project.get('dev-ideas')

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
''', epilog='''''')
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
