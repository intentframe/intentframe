> uv run email-sync-daemon reset --all                                       
Workspace: ~/.intentframe/email
This will delete ALL data including config.
Are you sure? [y/N] y
2026-03-18 02:55:07 [info     ] workspace_reset                deleted={'db': True, 'attachments': True, 'pid': False, 'config': True} home=~/.intentframe/email include_config=True
Deleted: database, attachments, config
 ~/intentframe                                                                                    
> uv run email-sync-daemon start                            
No config found at ~/.intentframe/email/config.yaml. Add an account first:
  email-sync-daemon add you@gmail.com
 ~/intentframe                                                                                    
> uv run email-sync-daemon add "user@gmail.com" -p "<app-password>"
2026-03-18 02:55:23 [info     ] imap_login_ok                  email=user@gmail.com provider=gmail
2026-03-18 02:55:23 [info     ] account_added                  config_path=~/.intentframe/email/config.yaml email=user@gmail.com
Added user@gmail.com (gmail, imap.gmail.com)
Restart the daemon to start syncing this account.
 ~/intentframe                                                                                    
> uv run email-sync-daemon start                            
2026-03-17T21:25:28.869410Z [info     ] daemon_starting                accounts=['user@gmail.com'] body_sync_days=90 db_path=~/.intentframe/email/emails.db
2026-03-17T21:25:30.694394Z [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-17T21:25:30.694880Z [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=Unwanted role=None
2026-03-17T21:25:30.695021Z [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-17T21:25:30.695130Z [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-17T21:25:30.695237Z [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-17T21:25:30.695330Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-17T21:25:30.695421Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-17T21:25:30.695504Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-17T21:25:30.695580Z [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged
2026-03-17T21:25:30.695674Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Trash role=trash
2026-03-17T21:25:30.695838Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-17T21:26:49.759151Z [info     ] sync_folder_done               account=user@gmail.com fetched=1449 headers_only=False inserted=1449 mailbox=INBOX
2026-03-17T21:26:49.764624Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox='[Gmail]/Sent Mail'
2026-03-17T21:26:52.747293Z [info     ] sync_folder_done               account=user@gmail.com fetched=4 headers_only=False inserted=3 mailbox='[Gmail]/Sent Mail'
2026-03-17T21:26:53.123326Z [info     ] priority_sync_done             account=user@gmail.com body_sync_days=90 new_messages=1452
2026-03-17T21:26:53.123822Z [info     ] daemon_running                 tasks=3
2026-03-17T21:26:53.125458Z [debug    ] pid_file_written               path=~/.intentframe/email/daemon.pid pid=3172
2026-03-17T21:26:53.125668Z [info     ] idle_start                     account=user@gmail.com
2026-03-17T21:26:53.125872Z [info     ] backfill_start                 account=user@gmail.com
2026-03-17T21:26:54.355660Z [info     ] sync_folder_start              account=user@gmail.com full=True headers_only=True mailbox=INBOX
2026-03-17T21:42:00.379972Z [info     ] sync_folder_done               account=user@gmail.com fetched=36508 headers_only=True inserted=35055 mailbox=INBOX
2026-03-17T21:42:00.470525Z [info     ] sync_folder_start              account=user@gmail.com full=True headers_only=True mailbox='[Gmail]/Sent Mail'
2026-03-17T21:42:07.277623Z [info     ] sync_folder_done               account=user@gmail.com fetched=214 headers_only=True inserted=208 mailbox='[Gmail]/Sent Mail'
2026-03-17T21:42:10.788184Z [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-17T21:42:10.788447Z [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=Unwanted role=None
2026-03-17T21:42:10.788573Z [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-17T21:42:10.788680Z [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-17T21:42:10.788801Z [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-17T21:42:10.788900Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-17T21:42:10.788998Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-17T21:42:10.789083Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-17T21:42:10.789162Z [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged
2026-03-17T21:42:10.789239Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Trash role=trash
2026-03-17T21:42:10.789414Z [info     ] sync_progress                  account=user@gmail.com folder=Unwanted folder_num=1 folder_total=6 headers_only=True
2026-03-17T21:42:10.789572Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=Unwanted
2026-03-17T21:42:13.348199Z [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=True inserted=0 mailbox=Unwanted
2026-03-17T21:42:13.348476Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Drafts folder_num=2 folder_total=6 headers_only=True
2026-03-17T21:42:13.348614Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Drafts
2026-03-17T21:42:15.814367Z [info     ] sync_folder_done               account=user@gmail.com fetched=18 headers_only=True inserted=18 mailbox=[Gmail]/Drafts
2026-03-17T21:42:15.814485Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Important folder_num=3 folder_total=6 headers_only=True
2026-03-17T21:42:15.814524Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Important
2026-03-17T21:42:41.513734Z [info     ] sync_folder_done               account=user@gmail.com fetched=1142 headers_only=True inserted=11 mailbox=[Gmail]/Important
2026-03-17T21:42:41.516322Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Spam folder_num=4 folder_total=6 headers_only=True
2026-03-17T21:42:41.516351Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Spam
2026-03-17T21:42:46.381642Z [info     ] sync_folder_done               account=user@gmail.com fetched=26 headers_only=True inserted=26 mailbox=[Gmail]/Spam
2026-03-17T21:42:46.381759Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Starred folder_num=5 folder_total=6 headers_only=True
2026-03-17T21:42:46.381786Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Starred
2026-03-17T21:42:52.585986Z [info     ] sync_folder_done               account=user@gmail.com fetched=16 headers_only=True inserted=0 mailbox=[Gmail]/Starred
2026-03-17T21:42:52.586116Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Trash folder_num=6 folder_total=6 headers_only=True
2026-03-17T21:42:52.586150Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Trash
2026-03-17T21:42:53.912049Z [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=True inserted=0 mailbox=[Gmail]/Trash
2026-03-17T21:42:55.580340Z [info     ] upgrade_progress               account=user@gmail.com folder=Unwanted folder_num=1 folder_total=6
2026-03-17T21:42:55.581613Z [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Drafts folder_num=2 folder_total=6
2026-03-17T21:42:55.582378Z [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Important folder_num=3 folder_total=6
2026-03-17T21:42:55.582987Z [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Spam folder_num=4 folder_total=6
2026-03-17T21:42:55.583525Z [info     ] upgrade_bodies_start           account=user@gmail.com count=26 mailbox=[Gmail]/Spam
2026-03-17T21:42:59.705545Z [info     ] upgrade_bodies_done            account=user@gmail.com mailbox=[Gmail]/Spam upgraded=26
2026-03-17T21:42:59.705671Z [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Starred folder_num=5 folder_total=6
2026-03-17T21:42:59.705820Z [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Trash folder_num=6 folder_total=6
2026-03-17T21:43:52.441427Z [info     ] integrity_check_done           account=user@gmail.com local=36770 ok=True server=37924
2026-03-17T21:43:52.448396Z [info     ] backfill_integrity_ok          account=user@gmail.com local=36770 server=37924
2026-03-17T21:43:52.449889Z [info     ] backfill_done                  account=user@gmail.com
2026-03-17T21:43:53.758109Z [info     ] sync_progress                  account=user@gmail.com folder=INBOX folder_num=1 folder_total=8 headers_only=False
2026-03-17T21:43:53.758195Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-17T21:43:57.220824Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=INBOX
2026-03-17T21:43:57.221004Z [info     ] sync_progress                  account=user@gmail.com folder=Unwanted folder_num=2 folder_total=8 headers_only=False
2026-03-17T21:43:57.221063Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=Unwanted
2026-03-17T21:43:58.831158Z [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=False inserted=0 mailbox=Unwanted
2026-03-17T21:43:58.831428Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Drafts folder_num=3 folder_total=8 headers_only=False
2026-03-17T21:43:58.831562Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Drafts
2026-03-17T21:44:01.296548Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Drafts
2026-03-17T21:44:01.296608Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Important folder_num=4 folder_total=8 headers_only=False
2026-03-17T21:44:01.296633Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Important
2026-03-17T21:44:03.634665Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Important
2026-03-17T21:44:03.634777Z [info     ] sync_progress                  account=user@gmail.com folder='[Gmail]/Sent Mail' folder_num=5 folder_total=8 headers_only=False
2026-03-17T21:44:03.634822Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox='[Gmail]/Sent Mail'
2026-03-17T21:44:06.792802Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox='[Gmail]/Sent Mail'
2026-03-17T21:44:06.793002Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Spam folder_num=6 folder_total=8 headers_only=False
2026-03-17T21:44:06.793090Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Spam
2026-03-17T21:44:08.898558Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Spam
2026-03-17T21:44:08.898755Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Starred folder_num=7 folder_total=8 headers_only=False
2026-03-17T21:44:08.898843Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Starred
2026-03-17T21:44:11.698487Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Starred
2026-03-17T21:44:11.698692Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Trash folder_num=8 folder_total=8 headers_only=False
2026-03-17T21:44:11.698786Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Trash
2026-03-17T21:44:13.326044Z [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=False inserted=0 mailbox=[Gmail]/Trash
2026-03-17T21:44:13.955276Z [info     ] periodic_sync_done             account=user@gmail.com new_messages=0
2026-03-17T21:45:53.710048Z [info     ] integrity_check_done           account=user@gmail.com local=36770 ok=True server=37924
2026-03-17T21:45:53.717990Z [info     ] periodic_integrity_ok          account=user@gmail.com local=36770 server=37924
2026-03-17T21:50:55.531408Z [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-17T21:50:55.531683Z [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=Unwanted role=None
2026-03-17T21:50:55.531814Z [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-17T21:50:55.531935Z [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-17T21:50:55.532049Z [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-17T21:50:55.532150Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-17T21:50:55.532238Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-17T21:50:55.532322Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-17T21:50:55.532401Z [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged
2026-03-17T21:50:55.532479Z [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Trash role=trash
2026-03-17T21:50:55.532607Z [info     ] sync_progress                  account=user@gmail.com folder=INBOX folder_num=1 folder_total=8 headers_only=False
2026-03-17T21:50:55.532725Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-17T21:50:57.916593Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=INBOX
2026-03-17T21:50:57.916783Z [info     ] sync_progress                  account=user@gmail.com folder=Unwanted folder_num=2 folder_total=8 headers_only=False
2026-03-17T21:50:57.916862Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=Unwanted
2026-03-17T21:51:00.291233Z [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=False inserted=0 mailbox=Unwanted
2026-03-17T21:51:00.291507Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Drafts folder_num=3 folder_total=8 headers_only=False
2026-03-17T21:51:00.291648Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Drafts
2026-03-17T21:51:03.352586Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Drafts
2026-03-17T21:51:03.352680Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Important folder_num=4 folder_total=8 headers_only=False
2026-03-17T21:51:03.352791Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Important
2026-03-17T21:51:05.390224Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Important
2026-03-17T21:51:05.390431Z [info     ] sync_progress                  account=user@gmail.com folder='[Gmail]/Sent Mail' folder_num=5 folder_total=8 headers_only=False
2026-03-17T21:51:05.390521Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox='[Gmail]/Sent Mail'
2026-03-17T21:51:07.572370Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox='[Gmail]/Sent Mail'
2026-03-17T21:51:07.572473Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Spam folder_num=6 folder_total=8 headers_only=False
2026-03-17T21:51:07.572520Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Spam
2026-03-17T21:51:09.479861Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Spam
2026-03-17T21:51:09.480170Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Starred folder_num=7 folder_total=8 headers_only=False
2026-03-17T21:51:09.480305Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Starred
2026-03-17T21:51:12.243848Z [info     ] sync_folder_done               account=user@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Starred
2026-03-17T21:51:12.243917Z [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Trash folder_num=8 folder_total=8 headers_only=False
2026-03-17T21:51:12.243946Z [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=[Gmail]/Trash
2026-03-17T21:51:13.799972Z [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=False inserted=0 mailbox=[Gmail]/Trash
2026-03-17T21:51:14.404370Z [info     ] periodic_sync_done             account=user@gmail.com new_messages=0
2026-03-17T21:52:06.030141Z [info     ] integrity_check_done           account=user@gmail.com local=36770 ok=True server=37924
2026-03-17T21:52:06.032221Z [info     ] periodic_integrity_ok          account=user@gmail.com local=36770 server=37924