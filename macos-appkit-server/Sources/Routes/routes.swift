import Vapor

func registerRoutes(_ app: Application, dispatcher: ServiceDispatcher) throws {
    app.get("health") { req async throws -> HealthResponse in
        let permissions = await dispatcher.checkPermissions()
        return HealthResponse(
            status: "ok",
            service: "platform-server",
            permissions: permissions
        )
    }

    app.get("permissions") { req async throws -> PermissionStatus in
        await dispatcher.checkPermissions()
    }

    app.post("execute") { req async throws -> ExecuteResponse in
        let request = try req.content.decode(ExecuteRequest.self)
        return await dispatcher.execute(
            adapter: request.adapter,
            action: request.action,
            params: request.params
        )
    }

    app.post("rollback") { req async throws -> ExecuteResponse in
        let request = try req.content.decode(RollbackRequest.self)
        return await dispatcher.rollback(
            adapter: request.adapter,
            rollbackId: request.rollback_id
        )
    }

    app.post("shutdown") { req async throws -> [String: String] in
        req.logger.info("Shutdown requested via API")
        Task {
            try? await Task.sleep(for: .milliseconds(200))
            try? await app.asyncShutdown()
            Foundation.exit(0)
        }
        return ["status": "shutting_down"]
    }
}
