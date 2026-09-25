from typing import Annotated, cast

from fastapi import Depends, Request

from src.database.repository import Repository


def get_repository(request: Request) -> Repository:
    return cast(Repository, request.app.state.repository)


RepositoryDependency = Annotated[Repository, Depends(get_repository)]
