""" HTTPサーバの実行 """
import uvicorn
import sukusute_server

uvicorn.run(sukusute_server.app)
