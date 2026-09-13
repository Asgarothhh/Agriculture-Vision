# docker build -f core/docker/Dockerfile core
FROM pytorch/pytorch:2.3.0-cuda11.8-cudnn8-devel

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/app/
WORKDIR /usr/app/

COPY requirements.txt /usr/app/
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8888

CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]