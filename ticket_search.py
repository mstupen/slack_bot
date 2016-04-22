 #!/usr/bin/env python

import argparse
import json
import os
import sys
from redmine import Redmine
from slackclient import SlackClient
from time import sleep
import re

from config import BOT_USER, REDMINE_KEY, REDMINE_URL, AUTH_TOKEN, REDMINE_USERS

import time



class MessageProcessor:
    """Will check all messages for you."""

    RE_HELP = re.compile(r'^help$')
    RE_ISSUE_FROM_LINK = re.compile(r'com/issues/(?P<issue_id>\d{3,5})')
    RE_ISSUE_INFO = re.compile(r'^issue (?P<issue_id>\d{3,5})$')
    RE_ISSUE_SET_STATUS = re.compile(r'^issue (?P<issue_id>\d{3,5}) status (?P<status_name>.*)$')
    RE_ISSUE_ASSIGN = re.compile(r'^issue (?P<issue_id>\d{3,5}) assign (?P<user_name>.*)$')

    def __init__(self):
        self.redmine = Redmine(REDMINE_URL, key=REDMINE_KEY, requests={'verify': False})

    def get_issue_repr(self, issue):
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

    def process(self, message):
        """Magic method"""

        text = message['text'].lower()

        m = self.RE_HELP.match(text)
        if m:
            response = self.process_message_help()
            return response

        m = self.RE_ISSUE_FROM_LINK.search(text)
        if m:
            response = self.process_message_issue_info(m.group('issue_id'))
            return response

        m = self.RE_ISSUE_INFO.match(text)
        if m:
            response = self.process_message_issue_info(m.group('issue_id'))
            return response

        m = self.RE_ISSUE_SET_STATUS.match(text)
        if m:
            response = self.process_message_issue_set_status(m.group('issue_id'), m.group('status_name'))
            return response

        m = self.RE_ISSUE_ASSIGN.match(text)
        if m:
            response = self.process_message_issue_assign(m.group('issue_id'), m.group('user_name'))
            return response

class Bot:
    """This is a super bot"""
    client = None
    my_user_name = ''

    def __init__(self, token, debug):
        self.client = SlackClient(token)
        self.client.rtm_connect()
        self.debug = debug
        self.my_user_name = self.client.server.username
        self.mp = MessageProcessor()
        print 'Connected to Slack.'

    # def _skip_processing(self, action):
    #     skip = False
    #     actions = [ 'hello', 'user_typing', 'presence_change' ]
    #     if 'user' in action and action['user'] == BOT_USER:
    #         if self.debug:
    #             print 'Skip processing bot messages: ', action
    #             skip = True
    #     if 'type' in action and action['type'] in actions:
    #         if self.debug:
    #             print 'Skip processing action: ', action['type']
    #             skip = True
    #
    #     return skip


    def start(self):
        """Listens for messages from slack. endless"""
        while True:
            some_input = self.client.rtm_read()
            if some_input:
                for action in some_input:
                    # if not action or self._skip_processing(action):
                    #     break
                    if self.debug:
                        print 'Processing: ', action
                    if 'type' in action and action['type'] == "message":
                        # Uncomment to only respond to messages addressed to us.
                        # if 'text' in action
                        #     and action['text'].lower().startswith(self.my_user_name):
                        self.process_action(action)
            else:
                sleep(1)

    def process_action(self, action):
        response = self.mp.process(action)

        return self.reply(action['channel'], response)

    def reply(self, channel, message):
        chan = self.client.server.channels.find(channel)

        if not chan:
            raise Exception('Channel %s not found.' % (channel,) )
        return chan.send_message(message)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''
This script replies responses to trigger phrases.
Exec with:
ticket_search.py keys.json
''', epilog='')
    parser.add_argument('-d', action='store_true', help="Print debug output.")
    parser.add_argument('topics_file', type=str, nargs=1,
                        help='JSON of phrases/responses to read.')
    args = parser.parse_args()

    # Create a new Bot
    bot = Bot(AUTH_TOKEN, args.d)

    try:
        bot.start()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print 'Exception: ', e.message
