> uv run pytest external_data_ingestion/tests/test_integration.py -v -s 2>&1
======================================== test session starts ========================================
platform darwin -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- .venv/bin/python3
cachedir: .pytest_cache
rootdir: external_data_ingestion
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=session, asyncio_default_test_loop_scope=session
collected 71 items                                                                                  

external_data_ingestion/tests/test_integration.py::TestProviders::test_resolve_gmail PASSED
external_data_ingestion/tests/test_integration.py::TestProviders::test_resolve_outlook PASSED
external_data_ingestion/tests/test_integration.py::TestProviders::test_resolve_unknown_falls_back PASSED
external_data_ingestion/tests/test_integration.py::TestConfig::test_service_config_loaded PASSED
external_data_ingestion/tests/test_integration.py::TestConfig::test_db_path_is_temp PASSED
external_data_ingestion/tests/test_integration.py::TestDBSchema::test_required_tables_exist PASSED
external_data_ingestion/tests/test_integration.py::TestDBSchema::test_fts_virtual_table PASSED
external_data_ingestion/tests/test_integration.py::TestDBSchema::test_wal_mode_active PASSED
external_data_ingestion/tests/test_integration.py::TestDBSchema::test_foreign_keys_on PASSED
external_data_ingestion/tests/test_integration.py::TestFolderDiscovery::test_discover_folders_returns_inbox 2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Bin role=trash
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-18 13:47:53 [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged

  9 folders discovered:
    INBOX                           role=inbox
    [Gmail]                         role=None
    [Gmail]/All Mail                role=all
    [Gmail]/Bin                     role=trash
    [Gmail]/Drafts                  role=drafts
    [Gmail]/Important               role=None
    [Gmail]/Sent Mail               role=sent
    [Gmail]/Spam                    role=junk
    [Gmail]/Starred                 role=flagged
PASSED
external_data_ingestion/tests/test_integration.py::TestFolderDiscovery::test_discover_has_common_gmail_roles PASSED
external_data_ingestion/tests/test_integration.py::TestSync::test_full_inbox_sync 2026-03-18 13:47:53 [info     ] sync_folder_start              account=testuser@gmail.com full=True headers_only=False mailbox=INBOX
2026-03-18 13:47:57 [info     ] sync_folder_done               account=testuser@gmail.com fetched=11 headers_only=False inserted=11 mailbox=INBOX

  Full sync: 11 new, 11 total in INBOX
PASSED
external_data_ingestion/tests/test_integration.py::TestSync::test_sync_state_persisted   sync_state: uidvalidity=1, last_uid=11
PASSED
external_data_ingestion/tests/test_integration.py::TestSync::test_incremental_sync_idempotent 2026-03-18 13:47:57 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 13:48:00 [info     ] sync_folder_done               account=testuser@gmail.com fetched=1 headers_only=False inserted=0 mailbox=INBOX
  Incremental sync: 0 new (expected 0 or very few)
PASSED
external_data_ingestion/tests/test_integration.py::TestSync::test_events_written   Events in DB after sync: 11
PASSED
external_data_ingestion/tests/test_integration.py::TestSync::test_headers_raw_populated   headers_raw: 6899 chars (first 120: Delivered-To: testuser@gmail.com
Received: by 2002:a05:680c:5207:10b2:6e9:8a95:5db4 with SMTP id k7-n1csp822379oke;
 ...)
PASSED
external_data_ingestion/tests/test_integration.py::TestSendEmail::test_send_to_self 2026-03-18 13:48:03 [info     ] email_sent                     account=testuser@gmail.com subject='[emailsync_03ace700] send_test' to=['testuser@gmail.com']

  Sent: <177382188076.10469.4160412849163449279@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa>
PASSED
external_data_ingestion/tests/test_integration.py::TestSendEmail::test_send_with_html 2026-03-18 13:48:07 [info     ] email_sent                     account=testuser@gmail.com subject='[emailsync_03ace700] html_test' to=['testuser@gmail.com']
  Sent HTML email: <177382188395.10469.13350358097948237994@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa>
PASSED
external_data_ingestion/tests/test_integration.py::TestSendEmail::test_send_event_recorded PASSED
external_data_ingestion/tests/test_integration.py::TestDeliveryAndResync::test_sent_email_arrives_in_inbox 2026-03-18 13:48:12 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 13:48:15 [info     ] sync_folder_done               account=testuser@gmail.com fetched=2 headers_only=False inserted=2 mailbox=INBOX

  Arrived after 5s: <177382188076.10469.4160412849163449279@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa>
PASSED
external_data_ingestion/tests/test_integration.py::TestReplyForward::test_reply 2026-03-18 13:48:19 [info     ] email_sent                     account=testuser@gmail.com subject='Re: [emailsync_03ace700] send_test' to=['testuser@gmail.com']

  Replied to <177382188076.10469.4160412849163449279@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa>
PASSED
external_data_ingestion/tests/test_integration.py::TestReplyForward::test_forward 2026-03-18 13:48:22 [info     ] email_sent                     account=testuser@gmail.com subject='Fwd: [emailsync_03ace700] send_test' to=['testuser@gmail.com']
  Forwarded <177382188076.10469.4160412849163449279@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa> to testuser@gmail.com
PASSED
external_data_ingestion/tests/test_integration.py::TestDraft::test_create_draft 2026-03-18 13:48:28 [info     ] draft_created                  account=testuser@gmail.com subject='[emailsync_03ace700] draft_test'

  Draft created: [emailsync_03ace700] draft_test
PASSED
external_data_ingestion/tests/test_integration.py::TestDraft::test_draft_event_recorded PASSED
external_data_ingestion/tests/test_integration.py::TestFlagOperations::test_mark_read_then_unread 
  mark_read / mark_unread OK on <803f7251a745c9e0760b2f34e8c4cd958c91172b-20166281-111794073@google.com>
PASSED
external_data_ingestion/tests/test_integration.py::TestFlagOperations::test_flag_event_recorded PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_list_folders 
  list_folders: []
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_list_folders_have_roles   folder roles: set()
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_recent   get_recent: 10 emails
    2026-03-18T13:48:03+05:30 | testuser@gmail.com | [emailsync_03ace700] html_test
    2026-03-18T13:48:00+05:30 | testuser@gmail.com | [emailsync_03ace700] send_test
    2026-03-17T05:21:56+00:00 | no-reply@accounts.google.com | Security alert
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_email_existing   get_email: Business tip: Show up on Google Search and Maps
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_email_nonexistent PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_unread_count   get_unread_count: 13
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_message_count   get_message_count(INBOX): 13
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_message_count_empty_mailbox PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_email_headers_only_skips_body_fetch   get_email(headers_only=True): content_level stayed 0 (no lazy fetch)
PASSED
external_data_ingestion/tests/test_integration.py::TestClientReads::test_get_email_has_headers_raw   get_email headers_raw: 6899 chars
PASSED
external_data_ingestion/tests/test_integration.py::TestSearch::test_fts_finds_test_email 
  search('send_test'): 1 result(s)
PASSED
external_data_ingestion/tests/test_integration.py::TestSearch::test_fts_no_results_for_garbage PASSED
external_data_ingestion/tests/test_integration.py::TestThreadReconstruction::test_get_thread_on_reply 2026-03-18 13:48:33 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 13:48:37 [info     ] sync_folder_done               account=testuser@gmail.com fetched=2 headers_only=False inserted=2 mailbox=INBOX

  get_thread: 1 message(s) in thread
PASSED
external_data_ingestion/tests/test_integration.py::TestClientWrites::test_client_send 2026-03-18 13:48:41 [info     ] email_sent                     account=testuser@gmail.com subject='[emailsync_03ace700] client_send' to=['testuser@gmail.com']

  client.send: <177382191705.10469.2469782762459716795@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa>
PASSED
external_data_ingestion/tests/test_integration.py::TestClientWrites::test_client_create_draft 2026-03-18 13:48:45 [info     ] draft_created                  account=testuser@gmail.com subject='[emailsync_03ace700] client_draft'
  client.create_draft: [emailsync_03ace700] client_draft
PASSED
external_data_ingestion/tests/test_integration.py::TestObserver::test_event_listener_fires 2026-03-18 13:48:48 [info     ] email_sent                     account=testuser@gmail.com subject='[emailsync_03ace700] observer_test' to=['testuser@gmail.com']

  Observer received 1 event(s)
PASSED
external_data_ingestion/tests/test_integration.py::TestObserver::test_start_stop_listening_idempotent PASSED
external_data_ingestion/tests/test_integration.py::TestMoveEmail::test_move_to_trash_and_back 
  Moved <177382188076.10469.4160412849163449279@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa>: INBOX -> [Gmail]/Bin -> INBOX
PASSED
external_data_ingestion/tests/test_integration.py::TestMoveEmail::test_move_event_recorded PASSED
external_data_ingestion/tests/test_integration.py::TestDeleteEmail::test_send_then_delete 2026-03-18 13:49:00 [info     ] email_sent                     account=testuser@gmail.com subject='[emailsync_03ace700] delete_me' to=['testuser@gmail.com']
2026-03-18 13:49:05 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 13:49:08 [info     ] sync_folder_done               account=testuser@gmail.com fetched=4 headers_only=False inserted=3 mailbox=INBOX

  Email arrived after 5s
  Deleted <177382193637.10469.2903351638315308648@1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.ip6.arpa> from remote + local
PASSED
external_data_ingestion/tests/test_integration.py::TestDaemon::test_upsert_account 
  Account upserted: testuser@gmail.com
PASSED
external_data_ingestion/tests/test_integration.py::TestDaemon::test_upsert_folders_populates_table 
  _upsert_folders: 9 folders inserted, roles={'flagged', 'inbox', 'all', 'drafts', 'sent', 'junk', 'trash'}
PASSED
external_data_ingestion/tests/test_integration.py::TestDaemon::test_upsert_folders_idempotent PASSED
external_data_ingestion/tests/test_integration.py::TestDaemon::test_upsert_idempotent PASSED
external_data_ingestion/tests/test_integration.py::TestDaemon::test_sync_all_folders 2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Bin role=trash
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-18 13:49:13 [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged
2026-03-18 13:49:13 [info     ] sync_progress                  account=testuser@gmail.com folder=INBOX folder_num=1 folder_total=8 headers_only=False
2026-03-18 13:49:13 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 13:49:14 [info     ] sync_folder_done               account=testuser@gmail.com fetched=1 headers_only=False inserted=0 mailbox=INBOX
2026-03-18 13:49:14 [info     ] sync_progress                  account=testuser@gmail.com folder='[Gmail]/All Mail' folder_num=2 folder_total=8 headers_only=False
2026-03-18 13:49:14 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox='[Gmail]/All Mail'
2026-03-18 13:49:18 [info     ] sync_folder_done               account=testuser@gmail.com fetched=138 headers_only=False inserted=121 mailbox='[Gmail]/All Mail'
2026-03-18 13:49:18 [info     ] sync_progress                  account=testuser@gmail.com folder=[Gmail]/Bin folder_num=3 folder_total=8 headers_only=False
2026-03-18 13:49:18 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=[Gmail]/Bin
2026-03-18 13:49:19 [info     ] sync_folder_done               account=testuser@gmail.com fetched=0 headers_only=False inserted=0 mailbox=[Gmail]/Bin
2026-03-18 13:49:19 [info     ] sync_progress                  account=testuser@gmail.com folder=[Gmail]/Drafts folder_num=4 folder_total=8 headers_only=False
2026-03-18 13:49:19 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=[Gmail]/Drafts
2026-03-18 13:49:20 [info     ] sync_folder_done               account=testuser@gmail.com fetched=2 headers_only=False inserted=0 mailbox=[Gmail]/Drafts
2026-03-18 13:49:20 [info     ] sync_progress                  account=testuser@gmail.com folder=[Gmail]/Important folder_num=5 folder_total=8 headers_only=False
2026-03-18 13:49:20 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=[Gmail]/Important
2026-03-18 13:49:22 [info     ] sync_folder_done               account=testuser@gmail.com fetched=1 headers_only=False inserted=0 mailbox=[Gmail]/Important
2026-03-18 13:49:22 [info     ] sync_progress                  account=testuser@gmail.com folder='[Gmail]/Sent Mail' folder_num=6 folder_total=8 headers_only=False
2026-03-18 13:49:22 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox='[Gmail]/Sent Mail'
2026-03-18 13:49:23 [info     ] sync_folder_done               account=testuser@gmail.com fetched=8 headers_only=False inserted=0 mailbox='[Gmail]/Sent Mail'
2026-03-18 13:49:23 [info     ] sync_progress                  account=testuser@gmail.com folder=[Gmail]/Spam folder_num=7 folder_total=8 headers_only=False
2026-03-18 13:49:23 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=[Gmail]/Spam
2026-03-18 13:49:24 [info     ] sync_folder_done               account=testuser@gmail.com fetched=0 headers_only=False inserted=0 mailbox=[Gmail]/Spam
2026-03-18 13:49:24 [info     ] sync_progress                  account=testuser@gmail.com folder=[Gmail]/Starred folder_num=8 folder_total=8 headers_only=False
2026-03-18 13:49:24 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=[Gmail]/Starred
2026-03-18 13:49:25 [info     ] sync_folder_done               account=testuser@gmail.com fetched=0 headers_only=False inserted=0 mailbox=[Gmail]/Starred

  sync_all_folders: 121 new messages
    draft_created: 2
    email_deleted: 1
    email_moved: 2
    email_sent: 7
    flag_changed: 2
    new_email: 139
    sync_complete: 1
PASSED
external_data_ingestion/tests/test_integration.py::TestDaemon::test_daemon_graceful_shutdown 2026-03-18 13:49:27 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 13:49:28 [info     ] sync_folder_done               account=testuser@gmail.com fetched=1 headers_only=False inserted=0 mailbox=INBOX
2026-03-18 13:49:28 [info     ] sync_folder_start              account=testuser@gmail.com full=False headers_only=False mailbox='[Gmail]/Sent Mail'
2026-03-18 13:49:30 [info     ] sync_folder_done               account=testuser@gmail.com fetched=1 headers_only=False inserted=0 mailbox='[Gmail]/Sent Mail'
2026-03-18 13:49:30 [info     ] priority_sync_done             account=testuser@gmail.com body_sync_days=90 new_messages=0
2026-03-18 13:49:30 [info     ] daemon_running                 tasks=3
2026-03-18 13:49:30 [info     ] idle_start                     account=testuser@gmail.com
2026-03-18 13:49:30 [info     ] backfill_start                 account=testuser@gmail.com
2026-03-18 13:49:32 [info     ] sync_folder_start              account=testuser@gmail.com full=True headers_only=True mailbox=INBOX
2026-03-18 13:49:33 [info     ] sync_folder_done               account=testuser@gmail.com fetched=17 headers_only=True inserted=0 mailbox=INBOX
2026-03-18 13:49:33 [info     ] sync_folder_start              account=testuser@gmail.com full=True headers_only=True mailbox='[Gmail]/Sent Mail'
2026-03-18 13:49:33 [info     ] daemon_shutting_down          
2026-03-18 13:49:33 [info     ] idle_stopped                   account=testuser@gmail.com
2026-03-18 13:49:35 [info     ] sync_folder_done               account=testuser@gmail.com fetched=8 headers_only=True inserted=0 mailbox='[Gmail]/Sent Mail'
2026-03-18 13:49:35 [info     ] backfill_done                  account=testuser@gmail.com
2026-03-18 13:49:35 [info     ] daemon_stopped                

  Daemon started + shut down cleanly
PASSED
external_data_ingestion/tests/test_integration.py::TestMultiAccountStorage::test_same_message_id_two_accounts 
  Same message_id stored for 2 accounts
PASSED
external_data_ingestion/tests/test_integration.py::TestMultiAccountStorage::test_flag_update_scoped_to_account   Flag update scoped correctly
PASSED
external_data_ingestion/tests/test_integration.py::TestMultiAccountStorage::test_delete_scoped_to_account   Delete scoped correctly
PASSED
external_data_ingestion/tests/test_integration.py::TestAccountManagement::test_add_email_no_validate 2026-03-18 13:49:35 [info     ] account_added                  config_path=/tmp/pytest/email_sync_test0/config.yaml email=fake-test@example.org

  add_email: ['testuser@gmail.com', 'fake-test@example.org']
PASSED
external_data_ingestion/tests/test_integration.py::TestAccountManagement::test_add_email_idempotent 2026-03-18 13:49:35 [info     ] account_added                  config_path=/tmp/pytest/email_sync_test0/config.yaml email=fake-test@example.org
  add_email idempotent (update, no duplicate)
PASSED
external_data_ingestion/tests/test_integration.py::TestAccountManagement::test_remove_email 2026-03-18 13:49:35 [info     ] account_removed                config_path=/tmp/pytest/email_sync_test0/config.yaml email=fake-test@example.org
  remove_email OK
PASSED
external_data_ingestion/tests/test_integration.py::TestAccountManagement::test_remove_nonexistent   remove_email returns False for unknown
PASSED
external_data_ingestion/tests/test_integration.py::TestAccountManagement::test_list_configured_emails   list_configured_emails: ['testuser@gmail.com']
PASSED
external_data_ingestion/tests/test_integration.py::TestAccountManagement::test_client_list_accounts   client.list_accounts: ['testuser@gmail.com']
PASSED
external_data_ingestion/tests/test_integration.py::TestTieredSyncSchema::test_content_level_column_exists 
  content_level column exists in emails table
PASSED
external_data_ingestion/tests/test_integration.py::TestTieredSyncSchema::test_schema_version_is_3   schema_version = 3
PASSED
external_data_ingestion/tests/test_integration.py::TestTieredSyncSchema::test_full_sync_rows_have_content_level_1   138 emails with content_level=1 from full sync
PASSED
external_data_ingestion/tests/test_integration.py::TestHeadersOnlySync::test_extract_email_row_headers_only 
  _extract_email_row(headers_only=True) -> content_level=0, empty body
PASSED
external_data_ingestion/tests/test_integration.py::TestHeadersOnlySync::test_extract_email_row_full   _extract_email_row(headers_only=False) -> content_level=1, body populated
PASSED
external_data_ingestion/tests/test_integration.py::TestBodyUpgrade::test_upgrade_folder_bodies 2026-03-18 13:49:35 [info     ] upgrade_bodies_start           account=testuser@gmail.com count=1 mailbox=INBOX
2026-03-18 13:49:38 [info     ] upgrade_bodies_done            account=testuser@gmail.com mailbox=INBOX upgraded=1

  upgrade_folder_bodies: uid=1 restored to content_level=1
PASSED
external_data_ingestion/tests/test_integration.py::TestLazyBodyFetch::test_lazy_fetch_upgrades_content_level 2026-03-18 13:49:41 [info     ] on_demand_body_fetched         message_id=<803f7251a745c9e0760b2f34e8c4cd958c91172b-20166281-111794073@google.com>

  Lazy body fetch: <803f7251a745c9e0760b2f34e8c4cd958c91172b-20166281-111794073@google.com> upgraded to content_level=1
PASSED
external_data_ingestion/tests/test_integration.py::TestMetadataOnlyAttachments::test_store_attachments_metadata_only 
  _store_attachments(metadata_only=True): metadata stored, no payload
PASSED
external_data_ingestion/tests/test_integration.py::TestSummary::test_event_log_summary 
  ── Event log summary ──
    new_email             139
    email_sent            7
    flag_changed          2
    email_moved           2
    draft_created         2
    sync_complete         1
    email_deleted         1
    TOTAL                 154
PASSED
external_data_ingestion/tests/test_integration.py::TestSummary::test_email_count_summary 
  ── Email count by mailbox ──
    [Gmail]/All Mail                121
    INBOX                           17
PASSED
============================================================
CLEANUP: removing test emails from remote server...
CLEANUP: deleted 24 test email(s) from remote
CLEANUP: removing temp workspace /tmp/pytest/email_sync_test0
CLEANUP: done
============================================================


================================== 71 passed in 129.81s (0:02:09) ==================================

> uv run pytest external_data_ingestion/tests/test_backfill_e2e.py -v -s 2>&1
======================================== test session starts ========================================
platform darwin -- Python 3.14.0, pytest-9.0.2, pluggy-1.6.0 -- .venv/bin/python3
cachedir: .pytest_cache
rootdir: external_data_ingestion
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.3.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=session, asyncio_default_test_loop_scope=session
collected 15 items                                                                                  

external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_00_db_is_empty 
  Phase 0: DB is empty ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_01_priority_pass 2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=Unwanted role=None
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged
2026-03-18 02:30:25 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Trash role=trash
2026-03-18 02:30:25 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox=INBOX
2026-03-18 02:31:55 [info     ] sync_folder_done               account=user@gmail.com fetched=1449 headers_only=False inserted=1449 mailbox=INBOX
2026-03-18 02:31:55 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=False mailbox='[Gmail]/Sent Mail'
2026-03-18 02:32:01 [info     ] sync_folder_done               account=user@gmail.com fetched=4 headers_only=False inserted=3 mailbox='[Gmail]/Sent Mail'

  Phase 1 (priority pass): {'INBOX': 1449, '[Gmail]/Sent Mail': 3}  total=1452
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_02_after_priority_inbox_has_bodies   Phase 1 check: INBOX 1449 emails, all content_level=1 ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_03_after_priority_only_inbox_sent   Phase 1 check: only priority folders present {'[Gmail]/Sent Mail', 'INBOX'} ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_04_backfill_old_headers 2026-03-18 02:32:01 [info     ] sync_folder_start              account=user@gmail.com full=True headers_only=True mailbox=INBOX
2026-03-18 02:45:52 [info     ] sync_folder_done               account=user@gmail.com fetched=36508 headers_only=True inserted=35055 mailbox=INBOX
2026-03-18 02:45:52 [info     ] sync_folder_start              account=user@gmail.com full=True headers_only=True mailbox='[Gmail]/Sent Mail'
2026-03-18 02:46:02 [info     ] sync_folder_done               account=user@gmail.com fetched=214 headers_only=True inserted=208 mailbox='[Gmail]/Sent Mail'
  Phase 2.1: Sent old headers backfilled +208 (total 211), 3 still have bodies
  Phase 2.1: INBOX old headers backfilled +35055 (total 36504), 1449 still have bodies ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_05_backfill_other_headers 2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=INBOX role=inbox
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasNoChildren',) name=Unwanted role=None
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasChildren', '\\Noselect') name=[Gmail] role=None
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\All', '\\HasNoChildren') name='[Gmail]/All Mail' role=all
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\Drafts', '\\HasNoChildren') name=[Gmail]/Drafts role=drafts
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Important') name=[Gmail]/Important role=None
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Sent') name='[Gmail]/Sent Mail' role=sent
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Junk') name=[Gmail]/Spam role=junk
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\Flagged', '\\HasNoChildren') name=[Gmail]/Starred role=flagged
2026-03-18 02:46:04 [debug    ] discovered_folder              flags=('\\HasNoChildren', '\\Trash') name=[Gmail]/Trash role=trash
2026-03-18 02:46:04 [info     ] sync_progress                  account=user@gmail.com folder=Unwanted folder_num=1 folder_total=6 headers_only=True
2026-03-18 02:46:04 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=Unwanted
2026-03-18 02:46:06 [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=True inserted=0 mailbox=Unwanted
2026-03-18 02:46:06 [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Drafts folder_num=2 folder_total=6 headers_only=True
2026-03-18 02:46:06 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Drafts
2026-03-18 02:46:09 [info     ] sync_folder_done               account=user@gmail.com fetched=18 headers_only=True inserted=18 mailbox=[Gmail]/Drafts
2026-03-18 02:46:09 [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Important folder_num=3 folder_total=6 headers_only=True
2026-03-18 02:46:09 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Important
2026-03-18 02:46:38 [info     ] sync_folder_done               account=user@gmail.com fetched=1142 headers_only=True inserted=11 mailbox=[Gmail]/Important
2026-03-18 02:46:38 [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Spam folder_num=4 folder_total=6 headers_only=True
2026-03-18 02:46:38 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Spam
2026-03-18 02:46:39 [info     ] sync_folder_done               account=user@gmail.com fetched=26 headers_only=True inserted=26 mailbox=[Gmail]/Spam
2026-03-18 02:46:39 [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Starred folder_num=5 folder_total=6 headers_only=True
2026-03-18 02:46:39 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Starred
2026-03-18 02:46:41 [info     ] sync_folder_done               account=user@gmail.com fetched=16 headers_only=True inserted=0 mailbox=[Gmail]/Starred
2026-03-18 02:46:41 [info     ] sync_progress                  account=user@gmail.com folder=[Gmail]/Trash folder_num=6 folder_total=6 headers_only=True
2026-03-18 02:46:41 [info     ] sync_folder_start              account=user@gmail.com full=False headers_only=True mailbox=[Gmail]/Trash
2026-03-18 02:46:42 [info     ] sync_folder_done               account=user@gmail.com fetched=0 headers_only=True inserted=0 mailbox=[Gmail]/Trash
  Phase 2.2: folders now in DB = {'[Gmail]/Drafts', '[Gmail]/Sent Mail', '[Gmail]/Important', '[Gmail]/Spam', 'INBOX'}
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_06_backfill_other_bodies 2026-03-18 02:46:44 [info     ] upgrade_progress               account=user@gmail.com folder=Unwanted folder_num=1 folder_total=6
2026-03-18 02:46:44 [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Drafts folder_num=2 folder_total=6
2026-03-18 02:46:44 [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Important folder_num=3 folder_total=6
2026-03-18 02:46:44 [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Spam folder_num=4 folder_total=6
2026-03-18 02:46:44 [info     ] upgrade_bodies_start           account=user@gmail.com count=26 mailbox=[Gmail]/Spam
2026-03-18 02:46:47 [info     ] upgrade_bodies_done            account=user@gmail.com mailbox=[Gmail]/Spam upgraded=26
2026-03-18 02:46:47 [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Starred folder_num=5 folder_total=6
2026-03-18 02:46:47 [info     ] upgrade_progress               account=user@gmail.com folder=[Gmail]/Trash folder_num=6 folder_total=6
  Phase 2.3: upgraded 26 bodies in non-priority folders ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_07_no_all_mail_in_db   All Mail ([Gmail]/All Mail) correctly excluded: 0 rows ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_08_every_selectable_folder_synced   Note: folders synced but have 0 messages (normal for empty folders): {'[Gmail]/Starred', 'Unwanted', '[Gmail]/Trash'}
  All 8 selectable folders (excl All Mail) have sync_state ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_09_priority_folders_have_full_bodies   INBOX: 1449 recent messages, all have bodies ✓
  [Gmail]/Sent Mail: 3 recent messages, all have bodies ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_09b_body_content_not_empty   Sampled 20 content_level=1 rows — all have body content ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_09c_attachment_metadata   Note: 68 attachment rows with empty filename or zero size (0 inline, 68 non-inline)
    Non-inline content types: {'text/plain': 34, 'text/html': 34}
  59 emails with attachments — all have attachment rows ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_09d_attachment_download   Downloaded 'booking-details.ics' (469 bytes) from uid=35243 in INBOX ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_10_imap_uid_integrity 2026-03-18 02:47:32 [info     ] integrity_check_done           account=user@gmail.com local=36770 ok=True server=37924

  Folder                               Server   Local  Missing  XFolder
  ─────────────────────────────────── ─────── ─────── ──────── ────────
  INBOX                                 36508   36504       0        4  ✓
  Unwanted                                  0       0       0        0  ✓
  [Gmail]/Drafts                           18      18       0        0  ✓
  [Gmail]/Important                      1142      11       0     1131  ✓
  [Gmail]/Sent Mail                       214     211       0        3  ✓
  [Gmail]/Spam                             26      26       0        0  ✓
  [Gmail]/Starred                          16       0       0       16  ✓
  [Gmail]/Trash                             0       0       0        0  ✓
  ─────────────────────────────────── ─────── ─────── ──────── ────────
  TOTAL                                 37924   36770

  UID integrity check passed — all 37924 server UIDs accounted for (1154 cross-folder) ✓
PASSED
external_data_ingestion/tests/test_backfill_e2e.py::TestBackfillE2E::test_11_summary 
  ── Backfill E2E Summary ──
  Folder                                Total  Bodies  Headers-only
  ─────────────────────────────────── ─────── ─────── ─────────────
  INBOX                                 36504    1449         35055
  [Gmail]/Drafts                           18       0            18
  [Gmail]/Important                        11       0            11
  [Gmail]/Sent Mail                       211       3           208
  [Gmail]/Spam                             26      26             0
  ─────────────────────────────────── ─────── ─────── ─────────────
  TOTAL                                 36770    1478         35292

  sync_state rows: 8
  Folders with data: 5
PASSED
============================================================
CLEANUP: removing test emails from remote server...
CLEANUP: deleted 0 test email(s) from remote
CLEANUP: removing temp workspace /tmp/pytest/email_sync_test0
CLEANUP: done
============================================================


================================== 15 passed in 1040.10s (0:17:20) ==================================
------------
All 15 E2E tests passed in 17 minutes 20 seconds. No failures. Here's where the time went:

| Phase | What | Messages | Time | Why |
|---|---|---|---|---|
| test_01 priority pass | Full bodies for INBOX + Sent (90 days) | 1,449 + 3 | ~1m 36s | Downloading full RFC822 bodies for 1,452 emails |
| test_04 backfill headers | Headers-only for ALL INBOX + Sent | 36,508 + 214 | ~13m 51s | 36K+ headers — lightweight per message but massive volume |
| test_05 other folders | Headers for 6 remaining folders | ~1,202 | ~38s | Small folders, fast |
| test_06 body upgrade | Bodies for non-priority recent window | 26 (Spam) | ~3s | Only 26 messages needed bodies |
| test_10 integrity | UID comparison + cross-folder resolution | 37,924 UIDs | ~45s | UID lists + Message-ID fetches for candidates |

The 14-minute wall in test_04 is the real cost — your INBOX has **36,508 messages total**. Even headers-only, that's 36K IMAP `FETCH` operations (in batches of 50 = ~730 round-trips). That's unavoidable for a full historical backfill of an inbox that large.

---

Now the integrity table:

```
Folder                               Server   Local  Missing  XFolder
INBOX                                 36508   36504       0        4  ✓
[Gmail]/Important                      1142      11       0     1131  ✓
[Gmail]/Sent Mail                       214     211       0        3  ✓
[Gmail]/Starred                          16       0       0       16  ✓
```

**Server** = how many UIDs exist on the IMAP server for that folder.

**Local** = how many rows are stored in the local DB for that folder.

**Missing** = UIDs on the server that are truly absent locally. Zero everywhere — nothing is lost.

**XFolder** (cross-folder) = UIDs that *appear* missing from that folder locally but actually exist in the DB under a *different* folder. This is Gmail's label system at work.

Here's why: Gmail doesn't have real folders — it has labels. When you label an email "Important", Gmail exposes it in both `INBOX` and `[Gmail]/Important` as separate UIDs. But the sync engine stores each email once (keyed by `message_id`), under whichever folder synced it first. So:

- **INBOX: 36,508 server vs 36,504 local, 4 cross-folder** — 4 INBOX emails were already stored under another folder (likely Sent — a message you sent to yourself appears in both).

- **[Gmail]/Important: 1,142 server vs 11 local, 1,131 cross-folder** — Gmail tagged 1,142 messages as "Important", but 1,131 of those were already stored under INBOX. Only 11 were unique to Important (messages not in INBOX).

- **[Gmail]/Starred: 16 server vs 0 local, 16 cross-folder** — all 16 starred messages already exist under INBOX or another folder. Zero unique messages.

- **[Gmail]/Sent Mail: 214 server vs 211 local, 3 cross-folder** — 3 sent messages were already stored under INBOX (emails you sent to yourself).

The key number is **Missing = 0 everywhere**. That means every single UID on the server is accounted for in the local DB — either stored directly under that folder or stored under a different folder with the same `message_id`. The integrity check passed perfectly.