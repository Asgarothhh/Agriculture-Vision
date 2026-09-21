# Руководство по развертыванию MLOps-инфраструктуры Agriculture-Vision

Данный документ содержит пошаговую инструкцию по развертыванию полного стека проекта (MinIO, DVC, MLflow, Kubernetes, Prometheus, Grafana, Airflow) на новом сервере или локальном компьютере под управлением Linux.

---

## 1. Системные требования

 **Ресурсы:** минимум 4 CPU, 8 GB RAM, 20 GB диск

---

## 2. Развертывание локального окружения

### 2.1. Клонирование и виртуальное окружение
```bash
git clone [https://gitlab.com/denissarubnev/Agriculture-Vision.git](https://gitlab.com/denissarubnev/Agriculture-Vision.git)
cd Agriculture-Vision

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install dvc dvc-s3 mlflow boto3 uvicorn fastapi

docker run -d -p 9000:9000 -p 9001:9001 \
  --name minio \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadminpassword" \
  minio/minio server /data --console-address ":9001"

dvc remote modify minio url s3://agri-dvc-storage
dvc remote modify minio endpointurl http://localhost:9000
dvc remote modify minio access_key_id minioadmin
dvc remote modify minio secret_access_key minioadminpassword
dvc remote modify minio use_ssl false

# Загрузка актуальной версии датасета из MinIO
dvc pull

export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadminpassword
export MLFLOW_S3_ENDPOINT_URL=http://localhost:9000

mlflow server \
  --backend-store-uri sqlite:///mlflow.db \
  --default-artifact-root s3://agri-mlflow-artifacts \
  --host 0.0.0.0 \
  --port 5000 &

minikube start --cpus=4 --memory=8192

# Применение базовых настроек неймспейса и квот
kubectl apply -f k8s/namespace-and-quota.yaml
kubectl apply -f k8s/limit-range.yaml

# Применение манифеста приложения (FastAPI + Health Checks)
kubectl apply -f k8s/deployment.yaml

kubectl get pods -n ml-service

helm repo add prometheus-community [https://prometheus-community.github.io/helm-charts](https://prometheus-community.github.io/helm-charts)
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoringagro \
  --create-namespace

# Пароль от Grafana admin
kubectl --namespace monitoringagro get secrets prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 -d ; echo

# Проброс порта (открыть http://localhost:3000)
kubectl port-forward svc/prometheus-grafana 3000:80 -n monitoringagro

helm repo add apache-airflow [https://airflow.apache.org](https://airflow.apache.org)
helm repo update

helm install airflow apache-airflow/airflow \
  --namespace airflowagro \
  --create-namespace

# Проброс порта (открыть http://localhost:8080, логин/пароль: admin/admin)
kubectl port-forward svc/airflow-webserver 8080:8080 -n airflowagro

