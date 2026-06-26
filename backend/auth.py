from fastapi import Header, HTTPException


async def get_github_token(x_github_token: str = Header(alias="X-GitHub-Token")):
    if not x_github_token:
        raise HTTPException(status_code=401, detail="GitHub token required")
    return x_github_token
