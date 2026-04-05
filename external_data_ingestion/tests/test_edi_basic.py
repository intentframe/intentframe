
import asyncio

from external_data_ingestion.email.config import load_config
from external_data_ingestion.email.imap_connection import get_provider

config = load_config()
account = config.accounts[0]


async def main():
    provider = get_provider(account)
    async with provider.connection() as mb:
        totals = {}
        for fi in mb.folder.list():
            name = fi.name
            flags = fi.flags
            noselect = '\\Noselect' in flags
            if noselect:
                continue
            try:
                status = mb.folder.status(name)
                totals[name] = status.get('MESSAGES', 0)
            except Exception as e:
                totals[name] = f'ERROR: {e}'

    grand = 0
    for name, count in sorted(totals.items(), key=lambda x: -(x[1] if isinstance(x[1], int) else 0)):
        print(f'  {name:40s} {count:>8}')
        if isinstance(count, int):
            grand += count
    print(f'  {chr(9472) * 40} {chr(9472) * 8}')
    print(f"  {'TOTAL (sum of all folders)':40s} {grand:>8}")
    print()
    all_mail = totals.get('[Gmail]/All Mail', 0)
    without_all = grand - (all_mail if isinstance(all_mail, int) else 0)
    print(f'  All Mail alone:          {all_mail}')
    print(f'  Sum WITHOUT All Mail:    {without_all}')


asyncio.run(main())

