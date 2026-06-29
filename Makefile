# Stratum Build-Targets. Laufen in der WSL2-Bauumgebung.
# Auf Windows: wsl make <target>

SCHEMAS_DIR := schemas
PY_OUT      := core/models
GO_OUT      := cli/schema/generated.go
GO_PKG      := schema

.PHONY: codegen codegen-py codegen-go check-drift

codegen: codegen-py codegen-go

codegen-py:
	mkdir -p $(PY_OUT)
	uv run --extra dev datamodel-codegen \
		--input $(SCHEMAS_DIR) \
		--input-file-type jsonschema \
		--output $(PY_OUT) \
		--output-model-type pydantic_v2.BaseModel \
		--use-annotated \
		--strict-nullable \
		--reuse-model \
		--formatters black \
		--formatters isort \
		--target-python-version 3.12 \
		--disable-timestamp

codegen-go:
	mkdir -p $(dir $(GO_OUT))
	go run github.com/atombender/go-jsonschema@v0.23.1 \
		--output $(GO_OUT) \
		--package $(GO_PKG) \
		--struct-name-from-title \
		$(SCHEMAS_DIR)/events.schema.json

check-drift: codegen
	git diff --exit-code $(SCHEMAS_DIR) $(PY_OUT) $(GO_OUT)
