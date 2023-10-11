from .bot import main
from .errors import sentry
from .metrics import metrics

if __name__ == "__main__":
    with sentry(), metrics():
        main()
