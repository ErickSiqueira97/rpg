from app.config import load_dotenv
from app.factory import create_app

load_dotenv()
app = create_app()


def main() -> None:
    import uvicorn

    settings = app.state.settings
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
