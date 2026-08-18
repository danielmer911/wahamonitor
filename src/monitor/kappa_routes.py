from fastapi import APIRouter, HTTPException

from monitor.groups import list_groups, set_group_mapping


def create_kappa_router(conn, kappa_client) -> APIRouter:
    router = APIRouter()

    @router.get("/api/kappa/clients")
    def get_kappa_clients():
        if kappa_client is None:
            raise HTTPException(status_code=503, detail="Kappa is not configured")
        return kappa_client.list_clients()

    @router.get("/api/kappa/projects")
    def get_kappa_projects():
        if kappa_client is None:
            raise HTTPException(status_code=503, detail="Kappa is not configured")
        return kappa_client.list_projects()

    @router.get("/api/groups")
    def get_groups():
        return list_groups(conn)

    @router.put("/api/groups/{group_id}/mapping")
    def put_group_mapping(group_id: str, payload: dict):
        set_group_mapping(
            conn,
            group_id,
            kappa_client_id=payload.get("kappa_client_id"),
            kappa_project_id=payload.get("kappa_project_id"),
        )
        return {"status": "ok"}

    return router
