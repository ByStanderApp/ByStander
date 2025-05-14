# ByStander
This is the main bystander application repository, An A.I. emergency guidance application. Below is the instructions on running the project

## Prerequisites

Before you begin, ensure you have the following installed:
* Python 3.x
* pip (Python package installer)
* Dart SDK
* Flutter SDK
* Any other necessary packages for your Flutter project.

## Running the Project

Follow these steps to run the main project:

1.  **Navigate to the backend directory:**
    ```bash
    cd bystander_backend
    ```

2.  **Create a virtual environment (recommended):**
    * On macOS and Linux:
        ```bash
        python3 -m venv env
        source env/bin/activate
        ```
    * On Windows:
        ```bash
        python -m venv env
        .\env\Scripts\activate
        ```

3.  **Install backend dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Navigate to the guidance generation module:**
    ```bash
    cd guidance_generation
    ```

5.  **Run the guidance generation script:**
    ```bash
    python3 main.py
    ```

6.  **Navigate back to the project root and then to the frontend directory:**
    ```bash
    cd ..
    cd ..
    cd bystander_frontend
    ```

7.  **Run the Flutter project:**
    ```bash
    flutter run
    ```

8.  **Choose Chrome as the running device** when prompted by Flutter.

9.  **Open Chrome and change the screen type to a phone/mobile view.** This can usually be done through the browser's developer tools (e.g., by pressing `Ctrl+Shift+I` or `Cmd+Option+I` and then toggling the device toolbar).

## Running MLflow

Follow these steps to run the MLflow UI:

1.  **Navigate to the backend directory (if you are not already there):**
    ```bash
    cd bystander_backend
    ```
    *If you are in the `bystander_frontend` directory from the previous steps, you would use:*
    ```bash
    cd ../bystander_backend
    ```


2.  **Create a virtual environment (if you haven't already or if you prefer a separate one for MLflow):**
    * On macOS and Linux:
        ```bash
        python3 -m venv env_mlflow  # Or use the existing 'env'
        source env_mlflow/bin/activate # Or source env/bin/activate
        ```
    * On Windows:
        ```bash
        python -m venv env_mlflow # Or use the existing 'env'
        .\env_mlflow\Scripts\activate # Or .\env\Scripts\activate
        ```

3.  **Install dependencies (if you created a new environment or if they are not already installed):**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Navigate to the MLflow directory:**
    ```bash
    cd mlflow
    ```

5.  **Start the MLflow UI:**
    ```bash
    mlflow ui
    ```
    This will typically start the MLflow UI on `http://localhost:5000`.