""" すくすくステップ HTTPサーバ """

import uuid

import fastapi
import sqlalchemy
import sqlalchemy.orm

from sukusute_server import http_models, database_models

app = fastapi.FastAPI()

@app.get("/api/health", tags=["API"])
def health() -> http_models.Result:
    """ サーバが生きていればokを返す。 """
    return http_models.Result(status="ok")

@app.post("/api/push_data", tags=["API"])
async def push_data(data: http_models.ChildDataRecord,
                    dbsession: database_models.SessionDep) -> http_models.Result:
    """ データを受け取る """
    target_child = await dbsession.get(database_models.Child, data.child_id)
    if data.distances:
        for distance in data.distances:
            child = await dbsession.get(database_models.Child, distance.with_child)
            dbsession.add(database_models.ChildDistanceData(
                children={target_child, child},
                distance=distance.distance,
                date=distance.date
            ))
    if data.singledata:
        dbsession.add(database_models.SingleChildData(date=data.singledata.date, steps=data.singledata.steps))
    await dbsession.commit()
    return http_models.Result(status="ok")

@app.get("/api/children/{child_id:int}", tags=["API"])
async def child_info(child_id: int, dbsession: database_models.SessionDep) -> http_models.ChildDataResponse:
    """ Childのすべての情報 """
    #target_child = await dbsession.get(database_models.Child, child_id)
    target_child = (await dbsession.execute(
        sqlalchemy.select(database_models.Child) \
            .where(database_models.Child.child_id == child_id) \
            .options(
                sqlalchemy.orm.selectinload(database_models.Child.singledata),
                sqlalchemy.orm.selectinload(database_models.Child.distance_1)
                    .selectinload(database_models.ChildDistanceData.child_1),
                sqlalchemy.orm.selectinload(database_models.Child.distance_1)
                    .selectinload(database_models.ChildDistanceData.child_2),
                sqlalchemy.orm.selectinload(database_models.Child.distance_2)
                    .selectinload(database_models.ChildDistanceData.child_1),
                sqlalchemy.orm.selectinload(database_models.Child.distance_2)
                    .selectinload(database_models.ChildDistanceData.child_2))
            )
    ).scalar()
    if not target_child:
        raise fastapi.exceptions.HTTPException(404, "No such child found.")

    return http_models.ChildDataResponse(
        status="ok",
        child_id=target_child.child_id,
        name=target_child.name,
        device_id=target_child.device_id,
        singledata=[
            http_models.ChildSingleData(date=singledata.date, steps=singledata.steps)
            for singledata in target_child.singledata
        ],
        distancedata=[
            http_models.ChildDistanceData(
                date=distance.date,
                distance=distance.distance,
                with_child=[child for child in distance.children if child.child_id != child_id][0].child_id
            ) for distance in target_child.distances
        ]
    )

@app.post("/api/create_debug_child", tags=["API", "debug"])
async def api_create_debug_child(dbsession: database_models.SessionDep) -> http_models.Result:
    child = database_models.Child(name="Test Child", device_id=uuid.uuid4())
    dbsession.add(child)
    await dbsession.commit()
    return http_models.Result(status="ok")
