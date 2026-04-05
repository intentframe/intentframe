import Contacts
import Foundation

actor ContactsService {
    private let store = CNContactStore()

    private static let keysToFetch: [CNKeyDescriptor] = [
        CNContactIdentifierKey as CNKeyDescriptor,
        CNContactGivenNameKey as CNKeyDescriptor,
        CNContactFamilyNameKey as CNKeyDescriptor,
        CNContactMiddleNameKey as CNKeyDescriptor,
        CNContactOrganizationNameKey as CNKeyDescriptor,
        CNContactJobTitleKey as CNKeyDescriptor,
        CNContactDepartmentNameKey as CNKeyDescriptor,
        CNContactEmailAddressesKey as CNKeyDescriptor,
        CNContactPhoneNumbersKey as CNKeyDescriptor,
        CNContactPostalAddressesKey as CNKeyDescriptor,
        CNContactUrlAddressesKey as CNKeyDescriptor,
        CNContactBirthdayKey as CNKeyDescriptor,
        CNContactNoteKey as CNKeyDescriptor,
        CNContactImageDataAvailableKey as CNKeyDescriptor,
        CNContactTypeKey as CNKeyDescriptor,
        CNContactRelationsKey as CNKeyDescriptor,
        CNContactSocialProfilesKey as CNKeyDescriptor,
        CNContactNicknameKey as CNKeyDescriptor,
        CNContactFormatter.descriptorForRequiredKeys(for: .fullName),
    ]

    func requestAccess() async -> Bool {
        do {
            return try await store.requestAccess(for: .contacts)
        } catch {
            return false
        }
    }

    func checkAccess() -> Bool {
        CNContactStore.authorizationStatus(for: .contacts) == .authorized
    }

    private func ensureAccess() -> ExecuteResponse? {
        guard checkAccess() else {
            return .failure(.accessDenied(
                "Contacts access not granted. Grant in System Settings > Privacy & Security > Contacts"
            ))
        }
        return nil
    }

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        if let denied = ensureAccess() { return denied }

        switch action {
        case "SEARCH_CONTACTS":
            return searchContacts(params)
        case "GET_CONTACT":
            return getContact(params)
        case "ADD_CONTACT":
            return addContact(params)
        case "UPDATE_CONTACT":
            return updateContact(params)
        case "DELETE_CONTACT":
            return deleteContact(params)
        case "FETCH_ALL_CONTACT_EMAILS":
            return fetchAllContactEmails()
        case "FETCH_GROUP_CONTACT_EMAILS":
            return fetchGroupContactEmails(params)
        default:
            return .failure(.unknownAction(action, adapter: "contacts"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        if let denied = ensureAccess() { return denied }
        guard rollbackId.hasPrefix("contact:") else {
            return .failure("Invalid rollback ID")
        }
        let contactId = String(rollbackId.dropFirst("contact:".count))

        let predicate = CNContact.predicateForContacts(withIdentifiers: [contactId])
        guard let contact = try? store.unifiedContacts(
            matching: predicate, keysToFetch: Self.keysToFetch
        ).first else {
            return .failure(.notFound("Contact not found for rollback"))
        }

        let mutable = contact.mutableCopy() as! CNMutableContact
        let saveRequest = CNSaveRequest()
        saveRequest.delete(mutable)

        do {
            try store.execute(saveRequest)
            return .success(data: [
                "contact_id": .string(contactId),
                "rolled_back": .bool(true),
            ])
        } catch {
            return .failure(.operationFailed("Rollback failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Actions

    private func searchContacts(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let query = params["query"]?.stringValue, !query.isEmpty else {
            return .failure(.invalidInput("Search query required"))
        }
        let limit = params["limit"]?.intValue ?? 20

        let predicate = CNContact.predicateForContacts(matchingName: query)
        do {
            let contacts = try store.unifiedContacts(matching: predicate, keysToFetch: Self.keysToFetch)
            let results = contacts.prefix(limit).map { contactToDict($0) }
            return .success(data: [
                "contacts": .array(results.map { .object($0) }),
                "count": .int(results.count),
            ])
        } catch {
            return .failure(.operationFailed("Contacts search failed: \(error.localizedDescription)"))
        }
    }

    private func getContact(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let contactId = params["contact_id"]?.stringValue
        let name = params["name"]?.stringValue

        if let contactId {
            let predicate = CNContact.predicateForContacts(withIdentifiers: [contactId])
            if let contact = try? store.unifiedContacts(
                matching: predicate, keysToFetch: Self.keysToFetch
            ).first {
                return .success(data: contactToDict(contact))
            }
        }

        if let name {
            let predicate = CNContact.predicateForContacts(matchingName: name)
            if let contacts = try? store.unifiedContacts(matching: predicate, keysToFetch: Self.keysToFetch),
               let contact = contacts.first {
                return .success(data: contactToDict(contact))
            }
        }

        return .failure(.notFound("Contact not found"))
    }

    private func addContact(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let firstName = params["first_name"]?.stringValue ?? ""
        let lastName = params["last_name"]?.stringValue ?? ""
        let organization = params["organization"]?.stringValue ?? ""

        guard !firstName.isEmpty || !lastName.isEmpty || !organization.isEmpty else {
            return .failure(.invalidInput("At least first_name, last_name, or organization required"))
        }

        let contact = CNMutableContact()
        contact.givenName = firstName
        contact.familyName = lastName
        if !organization.isEmpty { contact.organizationName = organization }
        if let jobTitle = params["job_title"]?.stringValue { contact.jobTitle = jobTitle }
        if let nickname = params["nickname"]?.stringValue { contact.nickname = nickname }

        if let email = params["email"]?.stringValue {
            contact.emailAddresses = [
                CNLabeledValue(label: CNLabelWork, value: email as NSString)
            ]
        }

        if let phone = params["phone"]?.stringValue {
            contact.phoneNumbers = [
                CNLabeledValue(label: CNLabelPhoneNumberMobile, value: CNPhoneNumber(stringValue: phone))
            ]
        }

        if let notes = params["notes"]?.stringValue { contact.note = notes }

        let saveRequest = CNSaveRequest()
        saveRequest.add(contact, toContainerWithIdentifier: nil)

        do {
            try store.execute(saveRequest)
        } catch {
            return .failure(.operationFailed("Failed to add contact: \(error.localizedDescription)"))
        }

        let name = "\(firstName) \(lastName)".trimmingCharacters(in: .whitespaces)
        return .success(
            data: [
                "name": .string(name.isEmpty ? organization : name),
                "created": .bool(true),
                "contact_id": .string(contact.identifier),
            ],
            rollbackId: "contact:\(contact.identifier)"
        )
    }

    private func updateContact(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let contactId = params["contact_id"]?.stringValue else {
            return .failure(.invalidInput("contact_id is required"))
        }

        let predicate = CNContact.predicateForContacts(withIdentifiers: [contactId])
        guard let existing = try? store.unifiedContacts(
            matching: predicate, keysToFetch: Self.keysToFetch
        ).first else {
            return .failure(.notFound("Contact not found: \(contactId)"))
        }

        let contact = existing.mutableCopy() as! CNMutableContact

        if let v = params["first_name"]?.stringValue { contact.givenName = v }
        if let v = params["last_name"]?.stringValue { contact.familyName = v }
        if let v = params["organization"]?.stringValue { contact.organizationName = v }
        if let v = params["job_title"]?.stringValue { contact.jobTitle = v }
        if let v = params["nickname"]?.stringValue { contact.nickname = v }

        if let email = params["email"]?.stringValue {
            if contact.emailAddresses.isEmpty {
                contact.emailAddresses = [CNLabeledValue(label: CNLabelWork, value: email as NSString)]
            } else {
                var existing = contact.emailAddresses.map { $0.mutableCopy() as! CNLabeledValue<NSString> }
                existing[0] = CNLabeledValue(label: existing[0].label, value: email as NSString)
                contact.emailAddresses = existing
            }
        }

        if let phone = params["phone"]?.stringValue {
            if contact.phoneNumbers.isEmpty {
                contact.phoneNumbers = [CNLabeledValue(label: CNLabelPhoneNumberMobile, value: CNPhoneNumber(stringValue: phone))]
            } else {
                var existing = contact.phoneNumbers.map { $0.mutableCopy() as! CNLabeledValue<CNPhoneNumber> }
                existing[0] = CNLabeledValue(label: existing[0].label, value: CNPhoneNumber(stringValue: phone))
                contact.phoneNumbers = existing
            }
        }

        let saveRequest = CNSaveRequest()
        saveRequest.update(contact)

        do {
            try store.execute(saveRequest)
        } catch {
            return .failure(.operationFailed("Update failed: \(error.localizedDescription)"))
        }

        return .success(data: contactToDict(contact))
    }

    private func deleteContact(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let contactId = params["contact_id"]?.stringValue else {
            return .failure(.invalidInput("contact_id is required"))
        }

        let predicate = CNContact.predicateForContacts(withIdentifiers: [contactId])
        guard let existing = try? store.unifiedContacts(
            matching: predicate, keysToFetch: Self.keysToFetch
        ).first else {
            return .failure(.notFound("Contact not found: \(contactId)"))
        }

        let info = contactToDict(existing)
        let mutable = existing.mutableCopy() as! CNMutableContact
        let saveRequest = CNSaveRequest()
        saveRequest.delete(mutable)

        do {
            try store.execute(saveRequest)
            return .success(data: info)
        } catch {
            return .failure(.operationFailed("Delete failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Bulk Contact Lookups (for Policy Registry source resolution)

    private static let emailOnlyKeys: [CNKeyDescriptor] = [
        CNContactEmailAddressesKey as CNKeyDescriptor,
        CNContactFormatter.descriptorForRequiredKeys(for: .fullName),
    ]

    private func fetchAllContactEmails() -> ExecuteResponse {
        var emails: [AnyCodableValue] = []
        let request = CNContactFetchRequest(keysToFetch: Self.emailOnlyKeys)
        request.sortOrder = .userDefault

        do {
            try store.enumerateContacts(with: request) { contact, _ in
                for labeled in contact.emailAddresses {
                    emails.append(.string(labeled.value as String))
                }
            }
            return .success(data: [
                "emails": .array(emails),
                "count": .int(emails.count),
            ])
        } catch {
            return .failure(.operationFailed("Failed to enumerate contacts: \(error.localizedDescription)"))
        }
    }

    private func fetchGroupContactEmails(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let groupName = params["group"]?.stringValue, !groupName.isEmpty else {
            return .failure(.invalidInput("group name is required"))
        }

        do {
            let groups = try store.groups(matching: nil)
            guard let group = groups.first(where: { $0.name == groupName }) else {
                return .failure(.notFound("Group not found: \(groupName)"))
            }

            let predicate = CNContact.predicateForContactsInGroup(withIdentifier: group.identifier)
            let contacts = try store.unifiedContacts(matching: predicate, keysToFetch: Self.emailOnlyKeys)

            var emails: [AnyCodableValue] = []
            for contact in contacts {
                for labeled in contact.emailAddresses {
                    emails.append(.string(labeled.value as String))
                }
            }

            return .success(data: [
                "emails": .array(emails),
                "count": .int(emails.count),
                "group": .string(groupName),
            ])
        } catch {
            return .failure(.operationFailed("Failed to fetch group contacts: \(error.localizedDescription)"))
        }
    }

    // MARK: - Serialization

    private func contactToDict(_ contact: CNContact) -> [String: AnyCodableValue] {
        let fullName = CNContactFormatter.string(from: contact, style: .fullName)
            ?? "\(contact.givenName) \(contact.familyName)".trimmingCharacters(in: .whitespaces)

        var dict: [String: AnyCodableValue] = [
            "contact_id": .string(contact.identifier),
            "name": .string(fullName),
            "first_name": .string(contact.givenName),
            "last_name": .string(contact.familyName),
        ]

        if !contact.organizationName.isEmpty { dict["organization"] = .string(contact.organizationName) }
        if !contact.jobTitle.isEmpty { dict["job_title"] = .string(contact.jobTitle) }
        if !contact.nickname.isEmpty { dict["nickname"] = .string(contact.nickname) }

        if !contact.emailAddresses.isEmpty {
            dict["emails"] = .array(contact.emailAddresses.map { labeled in
                .object([
                    "label": .string(CNLabeledValue<NSString>.localizedString(forLabel: labeled.label ?? "")),
                    "value": .string(labeled.value as String),
                ])
            })
            dict["email"] = .string(contact.emailAddresses.first?.value as String? ?? "")
        }

        if !contact.phoneNumbers.isEmpty {
            dict["phones"] = .array(contact.phoneNumbers.map { labeled in
                .object([
                    "label": .string(CNLabeledValue<CNPhoneNumber>.localizedString(forLabel: labeled.label ?? "")),
                    "value": .string(labeled.value.stringValue),
                ])
            })
            dict["phone"] = .string(contact.phoneNumbers.first?.value.stringValue ?? "")
        }

        if !contact.postalAddresses.isEmpty {
            dict["addresses"] = .array(contact.postalAddresses.map { labeled in
                let addr = labeled.value
                return .object([
                    "label": .string(CNLabeledValue<CNPostalAddress>.localizedString(forLabel: labeled.label ?? "")),
                    "street": .string(addr.street),
                    "city": .string(addr.city),
                    "state": .string(addr.state),
                    "postal_code": .string(addr.postalCode),
                    "country": .string(addr.country),
                ])
            })
        }

        if let birthday = contact.birthday {
            var bd: [String: AnyCodableValue] = [:]
            if let year = birthday.year { bd["year"] = .int(year) }
            if let month = birthday.month { bd["month"] = .int(month) }
            if let day = birthday.day { bd["day"] = .int(day) }
            dict["birthday"] = .object(bd)
        }

        dict["contact_type"] = .string(contact.contactType == .person ? "person" : "organization")

        return dict
    }
}
