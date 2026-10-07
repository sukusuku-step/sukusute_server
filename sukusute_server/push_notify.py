import asyncio
import logging

import sqlalchemy
import pywebpush
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat, load_der_private_key

import sukusute_server.database_models
logger = logging.getLogger(__name__)

async def get_vapid_key(dbsession: sukusute_server.database_models.SessionDep) -> ec.EllipticCurvePrivateKey:
    if rec := await dbsession.scalar(sqlalchemy.select(sukusute_server.database_models.WebPushVAPIDKeys)):
        privkey = load_der_private_key(rec.key_der, None)
        if not isinstance(privkey, ec.EllipticCurvePrivateKey):
            raise TypeError("Found an invalid key as a vapid key.")
        return privkey
    privkey = ec.generate_private_key(ec.SECP256R1())
    priv_der = privkey.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    rec = sukusute_server.database_models.WebPushVAPIDKeys(key_der=priv_der)
    dbsession.add(rec)
    await dbsession.commit()
    return privkey

async def get_vapid_pubkey(dbsession: sukusute_server.database_models.SessionDep) -> bytes:
    privkey = await get_vapid_key(dbsession)
    pubkey = privkey.public_key()
    return pubkey.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

async def send_notification(dbsession: sukusute_server.database_models.SessionDep, msg: str) -> None:
    key = await get_vapid_key(dbsession)
    pywebpush.Vapid()
    for subscription in await dbsession.scalars(sqlalchemy.select(sukusute_server.database_models.WebPushSubscriptionInfo)):
        try:
            await asyncio.to_thread(pywebpush.webpush,
                subscription_info=subscription.subscription_info,
                data=msg,
                vapid_private_key=pywebpush.Vapid(private_key=key),
                vapid_claims={"sub": "mailto:okaits@okaits7534.net"} # 何らかのメールアドレスを指定する必要があるので、とりあえずこれで……
            )
        except pywebpush.WebPushException as exc:
            logger.error(f"通知送信に失敗しました: {exc}")

