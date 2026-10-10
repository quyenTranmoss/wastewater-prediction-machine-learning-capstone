from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import os
load_dotenv()

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from database.users import verify_user


#Creates the authentication router
router = APIRouter()

#Used to read Bearer tokens from protected requests
security = HTTPBearer()

#JWT settings
load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable is not set")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


#Defines what the /login endpoint expects
class LoginRequest(BaseModel):
    username: str
    password: str


#Creates a JWT after a successful login
def create_access_token(username: str):
    expiration = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": username,
        "exp": expiration
    }

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


#Login endpoint
@router.post("/login")
def login(credentials: LoginRequest):

    #database/users.py checks the username and Argon2 password hash
    if not verify_user(
        credentials.username,
        credentials.password
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    #Credentials were valid, so create a login token
    access_token = create_access_token(
        credentials.username
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


#Checks whether a JWT sent by the user is valid
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        username = payload.get("sub")

        if username is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token"
            )

        return username

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )


#Temporary protected route used to test authentication
@router.get("/protected")
def protected_route(
    username: str = Depends(get_current_user)
):
    return {
        "message": f"Welcome {username}. You are authenticated."
    }