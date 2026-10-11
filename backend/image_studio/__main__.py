import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description='Local Image Studio API + React frontend')
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument(
        '--no-browser', action='store_true', help='Accepted for desktop launcher compatibility'
    )
    args = parser.parse_args()
    uvicorn.run('image_studio.api.app:app', host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
