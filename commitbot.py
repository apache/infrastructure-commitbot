#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import asyncio
import yaml
import fnmatch
import os
import sys
import asfpy.pubsub
import irc.client
import irc.client_aio


MAX_LOG_LEN = 200


def files_touched(files):
    """Finds the root path of files touched by this commit, as well as returns a short summary of what was touched"""
    if isinstance(files, dict):  # svn returns a dict, we only care about the filenames, so convert to list
        files = list(files.keys())
    if not files:  # No files touched, likely a branch or tag was created/deleted
        return "", "No files touched"
    if len(files) == 1:  # Just one file, return that
        return files[0], files[0]
    paths = files[0].split("/")
    commit_files = 0
    commit_dirs = set()
    for file in files:
        commit_files += 1
        commit_dirs.add(os.path.dirname(file))
        while not file.startswith("/".join(paths)):
            paths.pop()
            if len(paths) == 0:
                break
    root_path = "/".join(paths)
    commit_dirs = len(commit_dirs) == 1 and "1 directory" or f"{len(commit_dirs)} directories"
    commit_files = commit_files == 1 and "1 file" or f"{commit_files} files"
    return root_path, f"{root_path} ({commit_files} in {commit_dirs})"


def format_message(payload):
    """Formats a commit payload into an IRC message"""
    commit = payload.get("commit")
    if not commit:  # Probably a still-alive ping, ignore
        return "", ""
    commit_type = commit.get("repository")
    commit_root, commit_files = files_touched(commit.get("files") or commit.get("changed", {}))
    if commit_type == "git":
        commit_subject = commit.get("subject")
        author = commit.get("email", "unknown@apache.org")
        commit_repo = commit.get("project")
        tag = commit.get("ref", "main").replace("refs/heads/", "").replace("refs/tags/", "")  # Strip refs/*/ away
        sha = commit.get("hash", "0000000")
        url = f"https://gitbox.apache.org/repos/asf?p={commit_repo}.git;h={sha}"
        return (
            f"git:{commit_repo}",
            f"\x033 {author}\x03 \x02{tag} * {sha}\x0f ({commit_files}) {url}: {commit_subject}",
        )
    else:  # if not git, then svn
        author = commit.get("committer", "unknown") + "@apache.org"
        commit_subject = commit.get("log", "No log provided")
        commit_subject = " ".join(commit_subject.split("\n"))
        if len(commit_subject) > MAX_LOG_LEN:
            commit_subject = commit_subject[: MAX_LOG_LEN - 3] + "..."
        revision = commit.get("id", "1")
        url = f"https://svn.apache.org/r{revision}"
        return f"svn:{commit_root}", f"\x033 {author}\x03 \x02r{revision}\x0f ({commit_files}) {url}: {commit_subject}"


class CommitbotClient(irc.client_aio.AioSimpleIRCClient):
    def __init__(self, config: dict):
        irc.client.SimpleIRCClient.__init__(self)
        self.config = config
        self.future = None

    def run(self):
        password = open(self.config["client"]["password"]).read().strip()
        self.connect(
            self.config["server"]["host"],
            self.config["server"]["port"],
            self.config["client"]["nick"],
            ircname=self.config["client"]["realname"],
            password=password,
        )
        try:
            self.start()
        finally:
            self.connection.disconnect()
            self.reactor.loop.close()

    def on_welcome(self, connection, event):
        for channel in self.config["channels"]:
            self.connection.join(channel)
            print(f"Joined {channel}")

        self.future = asyncio.ensure_future(self.pubsub_poll(), loop=connection.reactor.loop)

    def on_disconnect(self, connection, event):
        if self.future:
            self.future.cancel()
        sys.exit(0)

    async def pubsub_poll(self):
        async for payload in asfpy.pubsub.listen(self.config["pubsub_host"]):
            root, msg = format_message(payload)
            if msg:
                sent = False
                for channel, data in self.config["channels"].items():
                    for tag in data.get("tags", []):
                        if fnmatch.fnmatch(root, tag):
                            self.connection.privmsg(channel, msg)
                            sent = True
                            break
                if sent:
                    await asyncio.sleep(1)  # Don't flood too quickly
        self.connection.quit("Bye!")


def main():
    print("Starting CommitBot")
    config = yaml.safe_load(open("config.yaml"))
    bot = CommitbotClient(config)
    bot.run()


if __name__ == "__main__":
    main()
