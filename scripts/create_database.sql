CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role_id INT NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE processing_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES processing_tasks(id) ON DELETE CASCADE,
    file_path VARCHAR(255) NOT NULL,
    image_type VARCHAR(50) NOT NULL,
    crs VARCHAR(50) NOT NULL,
    coverage_area FLOAT,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE object_classes (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    geometry_type VARCHAR(50) NOT NULL
);

CREATE TABLE models_registry (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    task_type VARCHAR(50) NOT NULL
);

CREATE TABLE polygons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id UUID NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    model_id INT NOT NULL REFERENCES models_registry(id) ON DELETE RESTRICT,
    class_id INT NOT NULL REFERENCES object_classes(id) ON DELETE RESTRICT,
    geom GEOMETRY(Polygon) NOT NULL,
    needs_manual_check BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE crop_probabilities (
    polygon_id UUID NOT NULL REFERENCES polygons(id) ON DELETE CASCADE,
    crop_class_id INT NOT NULL REFERENCES object_classes(id) ON DELETE RESTRICT,
    probability FLOAT NOT NULL CHECK (probability >= 0.0 AND probability <= 1.0),
    PRIMARY KEY (polygon_id, crop_class_id)
);

CREATE TABLE point_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id UUID NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    model_id INT NOT NULL REFERENCES models_registry(id) ON DELETE RESTRICT,
    class_id INT NOT NULL REFERENCES object_classes(id) ON DELETE RESTRICT,
    geom GEOMETRY(Point) NOT NULL,
    radius_approx FLOAT,
    area_approx FLOAT
);

CREATE INDEX idx_polygons_geom ON polygons USING gist(geom);
CREATE INDEX idx_point_objects_geom ON point_objects USING gist(geom);
CREATE INDEX idx_images_task_id ON images(task_id);
CREATE INDEX idx_polygons_image_id ON polygons(image_id);
CREATE INDEX idx_point_objects_image_id ON point_objects(image_id);
CREATE INDEX idx_crop_probabilities_polygon ON crop_probabilities(polygon_id);