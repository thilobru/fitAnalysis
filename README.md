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

## Prerequisites

* **Docker:** You need Docker installed on your system to run the application using the provided image. Visit [docker.com](https://www.docker.com/get-started) to download and install it.
* **FIT Files:** You need your own `.fit` files from cycling activities containing power data.

## Running with Docker (Recommended)

This is the easiest way to run the application.

1.  **Pull the Docker Image:**
    Replace `your-github-username` with your actual GitHub username or organization name where the repository lives. Replace `latest` with a specific version tag if needed.
    ```bash
    docker pull ghcr.io/your-github-username/fit_analyzer:latest
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
      ghcr.io/your-github-username/fit_analyzer:latest
    ```
    * `-d`: Run the container in detached mode (in the background).
    * `-p 5000:5000`: Map port 5000 on your host machine to port 5000 inside the container (where Flask/Gunicorn is running).
    * `-v /path/on/host/to/fitfiles:/app/fitfiles`: **Crucial:** Mount your local FIT files directory into the `/app/fitfiles` directory inside the container, where the application expects to find them. Make sure the host path is correct!
    * `--name fit_analyzer_app`: Assign a convenient name to the running container.
    * `ghcr.io/...`: The Docker image to use.

4.  **Access the Application:**
    Open your web browser and navigate to `http://127.0.0.1:5000` (or `http://localhost:5000`).

5.  **Stopping the Container:**
    ```bash
    docker stop fit_analyzer_app
    ```

6.  **Removing the Container:**
    ```bash
    docker rm fit_analyzer_app
    ```

## Local Development Setup (Optional)

If you want to run the code directly without Docker for development:

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/your-github-username/fit_analyzer.git](https://www.google.com/search?q=https://github.com/your-github-username/fit_analyzer.git)
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
    pip install -r requirements.txt
    ```
4.  **Prepare FIT Files:**
    Create a directory named `fitfiles` within the project root and place your `.fit` files inside it.
5.  **Run the Flask Development Server:**
    ```bash
    flask run
    ```
6.  **Access the Application:**
    Open your web browser and navigate to `http://127.0.0.1:5000`.

## Configuration

* **FIT File Location:** The application expects `.fit` files to be in the `fitfiles` directory relative to `app.py` when run locally, or in the `/app/fitfiles` directory when run inside Docker (which should be mapped using a volume).
