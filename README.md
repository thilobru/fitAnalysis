# FIT Analyzer - Power Curve Generator

A web application to analyze `.fit` files, specifically focusing on calculating and visualizing cycling power curves based on aggregated data from multiple files within a selected date range.

## Features

* Processes multiple `.fit` files.
* Extracts timestamp and power data from `record` messages.
* Aggregates data across selected files.
* Calculates maximum average power for various durations (1s to 90min+).
* Provides a web interface to select date ranges.
* Visualizes the power curve using Chart.js.
* Containerized using Docker for easy deployment.
* Configurable via environment variables.
* Includes automated tests (unit & integration).

## Prerequisites

* **Docker:** You need Docker installed on your system to run the application using the provided image. Visit [docker.com](https://www.docker.com/get-started) to download and install it.
* **FIT Files:** You need your own `.fit` files from cycling activities containing power data.

## Running with Docker (Recommended)

This is the easiest way to run the application.

1.  **Pull the Docker Image:**
    Replace `latest` with a specific version tag if needed.
    ```bash
    docker pull ghcr.io/thilobru/fit_analyzer:latest
    ```

2.  **Prepare FIT Files Directory:**
    Create a directory on your host machine where your `.fit` files are located (e.g., `/home/user/my_fit_files` or `C:\Users\YourUser\Documents\FIT_Files`).

3.  **Run the Container:**
    Execute the following command in your terminal, replacing `/path/on/host/to/fitfiles` with the actual path to your FIT files directory from step 2.

    ```bash
    docker run -d \
      -p 5000:5000 \
      -v /path/on/host/to/fitfiles:/app/fitfiles \
      --name fit_analyzer_app \
      ghcr.io/thilobru/fit_analyzer:latest
    ```
    * `-d`: Run the container in detached mode (in the background).
    * `-p 5000:5000`: Map port 5000 on your host machine to port 5000 inside the container. You can change the host port if 5000 is already in use (e.g., `-p 8080:5000`).
    * `-v /path/on/host/to/fitfiles:/app/fitfiles`: **Crucial:** Mount your local FIT files directory into the `/app/fitfiles` directory inside the container. The application reads files from `/app/fitfiles` by default. Make sure the host path is correct!
    * `--name fit_analyzer_app`: Assign a convenient name to the running container.
    * `ghcr.io/...`: The Docker image to use.

4.  **Access the Application:**
    Open your web browser and navigate to `http://127.0.0.1:5000` (or `http://localhost:5000`). If you changed the host port in step 3, use that port instead (e.g., `http://localhost:8080`).

5.  **Stopping the Container:**
    ```bash
    docker stop fit_analyzer_app
    ```

6.  **Removing the Container:**
    ```bash
    docker rm fit_analyzer_app
    ```

## Configuration via Environment Variables

The application can be configured using environment variables, particularly useful when running via Docker:

* **`FIT_ANALYZER_FIT_DIR`**: Path *inside the container* where the application looks for `.fit` files.
    * Default: `/app/fitfiles`
    * **Note:** You typically control the *content* of this directory by mounting a host volume using the `-v` flag in `docker run`. You usually don't need to change this environment variable unless you change the mount point path in the `docker run` command (e.g., `-v /host/path:/data` then `-e FIT_ANALYZER_FIT_DIR=/data`).
* **`FIT_ANALYZER_HOST`**: Host address for the server to bind to inside the container.
    * Default: `0.0.0.0` (listens on all interfaces within the container)
* **`FIT_ANALYZER_PORT`**: Port for the server to listen on inside the container.
    * Default: `5000` (This is the port you map using `-p host:container`)
* **`WORKERS`**: Number of Gunicorn worker processes.
    * Default: `2`

Example overriding the port inside the container (less common, usually you just change the host port mapping):
```bash
docker run -d \
  -p 5001:5001 \
  -v /path/on/host/to/fitfiles:/app/fitfiles \
  -e FIT_ANALYZER_PORT=5001 \
  --name fit_analyzer_app \
  ghcr.io/thilobru/fit_analyzer:latest
```
Now access via `http://localhost:5001`.


## Local Development Setup (Optional)

If you want to run the code directly without Docker for development:

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/thilobru/fit_analyzer.git](https://github.com/thilobru/fit_analyzer.git)
    cd fit_analyzer
    ```
2.  **Create Virtual Environment:**
    ```bash
    python -m venv venv
    # Activate (Windows CMD): venv\Scripts\activate.bat
    # Activate (Windows PowerShell): venv\Scripts\Activate.ps1
    # Activate (macOS/Linux): source venv/bin/activate
    ```
3.  **Install Dependencies:**
    ```bash
    pip install -r requirements-dev.txt # Install app and dev dependencies
    ```
4.  **Prepare FIT Files:**
    Create a directory named `fitfiles` within the project root and place your `.fit` files inside it, OR set the `FIT_ANALYZER_FIT_DIR` environment variable to point to your FIT file location before running.
    ```bash
    # Example (Bash/Zsh):
    export FIT_ANALYZER_FIT_DIR=/path/to/your/fitfiles
    # Example (Windows CMD):
    set FIT_ANALYZER_FIT_DIR=C:\path\to\your\fitfiles
    # Example (Windows PowerShell):
    $env:FIT_ANALYZER_FIT_DIR="C:\path\to\your\fitfiles"
    ```
5.  **Run the Flask Development Server:**
    ```bash
    # Ensure FLASK_DEBUG is set if you want debug mode (optional)
    # export FLASK_DEBUG=1
    flask run
    ```
6.  **Access the Application:**
    Open your web browser and navigate to `http://127.0.0.1:5000` (or the address shown by Flask).

## Running Tests & Quality Checks

Ensure development dependencies are installed (`pip install -r requirements-dev.txt`).

* **Run all tests:**
  ```bash
  pytest
  ```
* **Run tests with coverage:**
  ```bash
  pytest --cov=app --cov-report=term-missing
  ```
* **Run static type checking:**
  ```bash
  mypy .
  ```
* **Run linter/formatter checks:**
  ```bash
  ruff check .
  ruff format --check .
  ```
