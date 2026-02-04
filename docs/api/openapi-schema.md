# OpenAPI Schema

The Databricks tellr API provides a complete OpenAPI 3.0 schema for programmatic access and API documentation.

## Accessing the Schema

### Interactive Swagger UI

When running the API locally, access the interactive Swagger UI at:

```
http://localhost:8000/docs
```

The Swagger UI provides:
- Complete API documentation
- Interactive endpoint testing
- Request/response schema definitions
- Authentication testing

### OpenAPI JSON Schema

Download the complete OpenAPI schema in JSON format:

```
http://localhost:8000/openapi.json
```

### ReDoc Documentation

Alternative documentation interface:

```
http://localhost:8000/redoc
```

## Schema Details

The OpenAPI schema includes:

- **All endpoints** - Complete API surface
- **Request schemas** - Pydantic models for all request bodies
- **Response schemas** - Response models with examples
- **Authentication** - Security scheme definitions
- **Error responses** - Standard error formats
- **Path parameters** - Parameter definitions and validation rules
- **Query parameters** - Query string parameter documentation

## Using the Schema

### Generate Client Libraries

Use tools like [OpenAPI Generator](https://openapi-generator.tech/) to generate client libraries:

```bash
openapi-generator generate \
  -i http://localhost:8000/openapi.json \
  -g python \
  -o ./generated-client
```

### API Testing

Import the schema into API testing tools:

- **Postman** - Import OpenAPI schema
- **Insomnia** - Import from OpenAPI URL
- **HTTPie** - Use with OpenAPI schema

### Documentation Generation

Use the schema to generate static documentation:

```bash
# Using redoc-cli
npx @redocly/cli build-docs http://localhost:8000/openapi.json
```

## Schema Version

The OpenAPI schema version matches the API version. Current version: `0.3.0`

## Example: Fetching the Schema

```bash
# Download schema
curl http://localhost:8000/openapi.json > openapi.json

# View in browser
open http://localhost:8000/docs
```

## Schema Structure

The OpenAPI schema is organized by tags:

- `sessions` - Session management
- `chat` - Chat and slide generation
- `slides` - Slide CRUD operations
- `export` - Export endpoints
- `verification` - Verification endpoints
- `settings` - Configuration management

Each tag includes all related endpoints with complete request/response documentation.

