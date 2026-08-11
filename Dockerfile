FROM alpine:latest
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_NO_DEV=1
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app
COPY pyproject.toml .python-version ./
RUN uv sync
COPY ./ ./
RUN rm data.sqlite ||true
RUN uv run alembic upgrade head
RUN uv run python3 add_child.py
CMD ["uv", "run", "--no-sync", "python3", "-m", "sukusute_server"]

EXPOSE 8000
