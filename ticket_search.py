#!/usr/bin/env python

import argparse
import sys
from redmine import Redmine
from slackclient import SlackClient
from time import sleep
import re

import config


class MessageProcessor(object):
    """Will check all messages for you."""

    RE_HELP = re.compile(r'^help$')
    RE_ISSUE_FROM_LINK = re.compile(r'com/issues/(?P<issue_id>\d{3,6})')
    RE_ISSUE_INFO = re.compile(r'^issue (?P<issue_id>\d{3,6})$')
    RE_ISSUE_SET_STATUS = re.compile(r'^issue (?P<issue_id>\d{3,6}) status (?P<status_name>.*)$')
    RE_ISSUE_ASSIGN = re.compile(r'^issue (?P<issue_id>\d{3,6}) assign (?P<user_name>.*)$')
    RE_ISSUES = re.compile(r'^issues (?P<user_name>.*)$')
    RE_ISSUE_ADD_CHILD = re.compile(r'^issue (?P<issue_id>\d{3,6}) add (?P<subject>.*)$')
    RE_ISSUE_ADD_NOTE = re.compile(r'^issue (?P<issue_id>\d{3,6}) note (?P<note>.*)$')
    RE_ISSUE_SET_SUBJECT = re.compile(r'^issue (?P<issue_id>\d{3,6}) subject (?P<subject>.*)$')
    RE_ISSUE_ASSIGN_AUTO = re.compile(r'^issue (?P<issue_id>\d{3,6}) assign$')
    RE_ISSUES_AUTO = re.compile(r'^issues$')

    MESSAGE_USER_NOT_FOUND = 'Unknown user, possible: %s' % ', '.join([i.capitalize() for i in config.REDMINE_USERS.keys()])

    def __init__(self):
        self.redmine = Redmine(config.REDMINE_URL, key=config.REDMINE_KEY, requests={'verify': False})

    def _get_issue_repr(self, issue):
        return u'*{id}*: _{subject}_ *{status}* {assignee}'.format(
            id=issue.id or 'Not saved',
            subject=issue.subject,
            status=issue.status if hasattr(issue, 'status') and issue.status else 'New',
            assignee=('(assigned to %s)' % issue.assigned_to) if hasattr(issue, 'assigned_to') and issue.assigned_to else '(unassigned)'
        )

    def _get_user_id_by_user_name(self, user_name):
        users = config.REDMINE_USERS

        if user_name in users:
            return users[user_name]

        user_name_lower = user_name.lower()
        if user_name_lower in users:
            return users[user_name_lower]

        return

    def _get_user_id_by_user_profile(self, user_profile):
        user_id = self._get_user_id_by_user_name(user_profile.get('email'))
        if user_id:
            return user_id

        user_id = self._get_user_id_by_user_name(user_profile.get('first_name'))
        if user_id:
            return user_id

        return

    def _get_issue_repr_detailed(self, issue):
        child_ids = [child.id for child in issue.children]
        children = [self.redmine.issue.get(child_id) for child_id in child_ids]
        return u'{info}{children}'.format(
            info=self._get_issue_repr(issue),
            children=(u''.join([u'\n    > %s' % self._get_issue_repr(i) for i in children])) if children else '',
        )

    def process_message_help(self):
        return u'\n'.join([
            '*help* - show help',
            '*issue <issue_id>* - show issue info',
            '*issue <issue_id> assign* - assign task to me',
            '*issue <issue_id> assign <user_name>* - change issue assignee',
            '*issue <issue_id> status <status>* - change issue status',
            '*issue <issue_id> subject <subject>* - change issue subject',
            '*issue <issue_id> note <note>* - add new note to description',
            '*issue <issue_id> add <subject>* - add new subtask to issue',
            '*issues <user_name>* - show all open issues for user',
            '*issues* - show all open issues assigned to me',
        ])

    def process_message_issue_add_child(self, issue_id, subject):
        issue = self.redmine.issue.get(issue_id)

        subtask = self.redmine.issue.new()
        subtask.subject = subject
        subtask.description = 'Was generated by redmine bot'
        subtask.parent_issue_id = issue.id
        subtask.project_id = issue.project.id
        if hasattr(issue, 'assigned_to'):
            subtask.assigned_to.id = issue.assigned_to_id

        subtask.save()

        issue = self.redmine.issue.get(issue_id, include='children')
        return self._get_issue_repr_detailed(issue)

    def process_message_issues(self, user_name):
        user_id = self._get_user_id_by_user_name(user_name)
        if user_id is None:
            return self.MESSAGE_USER_NOT_FOUND

        issues = [i for i in self.redmine.issue.filter(assigned_to_id=user_id, status='open')]
        issue_ids = [i.id for i in issues]

        stories = [i for i in issues if not hasattr(i, 'parent')]
        standalone_tickets = [i for i in issues if hasattr(i, 'parent') and i.parent.id not in issue_ids]
        standalone_tickets_str = '\n'.join(map(lambda issue: self._get_issue_repr(issue), standalone_tickets))

        return u'{stories}{tickets}{empty}'.format(
            stories=(u'*Stories:*\n%s\n\n' % '\n'.join(map(lambda issue: self._get_issue_repr(issue), stories))) if stories else u'',
            tickets=(u'*Standalone tickets:*\n%s\n\n' % standalone_tickets_str) if standalone_tickets else u'',
            empty=u'No issues found' if not stories and not standalone_tickets else u'',
        )

    def process_message_issues_auto(self, user_profile):
        user_id = self._get_user_id_by_user_profile(user_profile)
        if user_id is None:
            return self.MESSAGE_USER_NOT_FOUND

        issues = [i for i in self.redmine.issue.filter(assigned_to_id=user_id, status='open')]
        issue_ids = [i.id for i in issues]

        stories = [i for i in issues if not hasattr(i, 'parent')]
        standalone_tickets = [i for i in issues if hasattr(i, 'parent') and i.parent.id not in issue_ids]
        standalone_tickets_str = '\n'.join(map(lambda issue: self._get_issue_repr(issue), standalone_tickets))

        return u'{stories}{tickets}{empty}'.format(
            stories=(u'*Stories:*\n%s\n\n' % '\n'.join(map(lambda issue: self._get_issue_repr(issue), stories))) if stories else u'',
            tickets=(u'*Standalone tickets:*\n%s\n\n' % standalone_tickets_str) if standalone_tickets else u'',
            empty=u'No issues found' if not stories and not standalone_tickets else u'',
        )

    def process_message_issue_info(self, issue_id):
        issue = self.redmine.issue.get(issue_id, include='children')
        return self._get_issue_repr_detailed(issue)

    def process_message_issue_set_status(self, issue_id, status_name):
        issue = self.redmine.issue.get(issue_id)
        statuses = self.redmine.issue_status.all()

        set_status_id = None
        for status in statuses:
            if status.name.lower() == status_name.lower():
                set_status_id = status.id

        if set_status_id is None:
            return u'Unknown status, possible: %s' % ', '.join([i.name for i in statuses])

        issue.status_id = set_status_id
        issue.save()

        issue = self.redmine.issue.get(issue_id)
        return self._get_issue_repr(issue)

    def process_message_issue_assign(self, issue_id, user_name):
        issue = self.redmine.issue.get(issue_id)

        user_id = self._get_user_id_by_user_name(user_name)
        if user_id is None:
            return self.MESSAGE_USER_NOT_FOUND

        issue.assigned_to_id = user_id
        issue.save()

        issue = self.redmine.issue.get(issue_id)
        return self._get_issue_repr(issue)

    def process_message_issue_assign_auto(self, user_profile, issue_id):
        issue = self.redmine.issue.get(issue_id)

        user_id = self._get_user_id_by_user_profile(user_profile)
        if user_id is None:
            return self.MESSAGE_USER_NOT_FOUND

        issue.assigned_to_id = user_id
        issue.save()

        issue = self.redmine.issue.get(issue_id)
        return self._get_issue_repr(issue)

    def process_message_issue_set_subject(self, issue_id, subject):
        issue = self.redmine.issue.get(issue_id)
        issue.subject = subject
        issue.save()

        issue = self.redmine.issue.get(issue_id)
        return self._get_issue_repr(issue)

    def process_message_issue_add_note(self, user_profile, issue_id, note):
        issue = self.redmine.issue.get(issue_id)
        issue.description = '{old}\n\nh3. {title}\n\n{note}'.format(
            old=issue.description,
            title='Added via Slack by %s' % (user_profile['real_name']),
            note=note,
        )
        issue.save()
        return 'Description updated'

        # issue = self.redmine.issue.get(issue_id)
        # return self._get_issue_repr(issue)

    def process(self, message, user_info):
        """Magic method"""

        if 'text' not in message:
            return

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

        m = self.RE_ISSUES.match(text)
        if m:
            response = self.process_message_issues(m.group('user_name'))
            return response

        m = self.RE_ISSUE_ADD_CHILD.match(text)
        if m:
            response = self.process_message_issue_add_child(m.group('issue_id'), m.group('subject'))
            return response

        m = self.RE_ISSUE_SET_SUBJECT.match(text)
        if m:
            response = self.process_message_issue_set_subject(m.group('issue_id'), m.group('subject'))
            return response

        m = self.RE_ISSUE_ADD_NOTE.match(text)
        if m:
            response = self.process_message_issue_add_note(user_info, m.group('issue_id'), m.group('note'))
            return response

        m = self.RE_ISSUES_AUTO.match(text)
        if m:
            response = self.process_message_issues_auto(user_info)
            return response

        m = self.RE_ISSUE_ASSIGN_AUTO.match(text)
        if m:
            response = self.process_message_issue_assign_auto(user_info, m.group('issue_id'))
            return response


class Bot(object):
    """This is a super bot"""
    client = None
    my_user_name = ''

    def __init__(self, token, debug):
        self.client = SlackClient(token)
        self.client.rtm_connect()
        self.debug = debug
        self.my_user_name = self.client.server.username
        self.mp = MessageProcessor()
        self.users = {}
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
                    if self.debug:
                        print 'Processing: ', action

                    if 'type' not in action:
                        continue
                    if 'user' not in action:
                        continue
                    if action['type'] == "message":
                        try:
                            self.process_action(action)
                        except Exception as e:
                            if self.debug:
                                raise
                            print e
            else:
                sleep(1)

    def _get_user_profile_for_action(self, action):
        user_id = action['user']
        if user_id not in self.users:
            self.users[user_id] = self.client.api_call('users.info', user=action['user'])['user']['profile']

        return self.users[user_id]

    def process_action(self, action):
        user_info = self._get_user_profile_for_action(action)
        response = self.mp.process(action, user_info)
        if response is None:
            return

        return self.reply(action['channel'], response)

    def reply(self, channel, message):
        chan = self.client.server.channels.find(channel)

        if not chan:
            raise Exception('Channel %s not found.' % (channel, ))
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
    bot = Bot(config.AUTH_TOKEN, args.d)

    try:
        bot.start()
    except KeyboardInterrupt:
        sys.exit(0)
