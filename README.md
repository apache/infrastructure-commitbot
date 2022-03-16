# infrastructure-commitbot
ASF Commit Bot for IRC

## What does this do?
This is a simple IRC bot for displaying commit activity on IRC for committers and users to make use of.
It uses [`config.yaml`](config.yaml) for managing which channels to join and which tags to subscribe to.

If you have a channel or commit subscription that needs added, please make a PR.

The service runs on our ASFBot VM as a "pipservice" (think of it as a Python app) and refreshes when 
the config changes.

Any questions? Feel free to ask us on users@infra.apache.org then!
