---
name: apple-contacts
description: Manage Apple Contacts
version: "2.0"
metadata:
  os: ["darwin"]
---

# Apple Contacts

Search, view, and manage contacts on this Mac.

## Available Tools

- `search_contacts` — Search contacts by name query.
- `get_contact` — Get full details for a contact by `contact_id` or `name`.
- `add_contact` — Add a new contact. At least `first_name`, `last_name`, or `organization` required.
- `update_contact` — Update a contact by `contact_id`.
- `delete_contact` — Delete a contact by `contact_id`.

## Important

- Use `search_contacts` to find contacts before trying to get, update, or delete them.
- Get `contact_id` from search results before updating or deleting.
- Always use the dedicated tools above for contact operations.
