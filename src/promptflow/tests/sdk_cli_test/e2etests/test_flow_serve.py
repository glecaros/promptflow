import json
import os
import re

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from promptflow.core._serving.constants import FEEDBACK_TRACE_FIELD_NAME
from promptflow.core._serving.utils import load_feedback_swagger
from promptflow.tracing._operation_context import OperationContext


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_swagger(flow_serving_client):
    swagger_dict = json.loads(flow_serving_client.get("/swagger.json").data.decode())
    expected_swagger = {
        "components": {"securitySchemes": {"bearerAuth": {"scheme": "bearer", "type": "http"}}},
        "info": {
            "title": "Promptflow[basic-with-connection] API",
            "version": "1.0.0",
            "x-flow-name": "basic-with-connection",
        },
        "openapi": "3.0.0",
        "paths": {
            "/score": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {"text": "Hello World!"},
                                "schema": {
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                    "type": "object",
                                },
                            }
                        },
                        "description": "promptflow input data",
                        "required": True,
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"properties": {"output_prompt": {"type": "string"}}, "type": "object"}
                                }
                            },
                            "description": "successful operation",
                        },
                        "400": {"description": "Invalid input"},
                        "default": {"description": "unexpected error"},
                    },
                    "summary": "run promptflow: basic-with-connection with an given input",
                }
            }
        },
        "security": [{"bearerAuth": []}],
    }
    feedback_swagger = load_feedback_swagger()
    expected_swagger["paths"]["/feedback"] = feedback_swagger
    assert swagger_dict == expected_swagger


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_feedback_flatten(flow_serving_client):
    resource = Resource(
        attributes={
            SERVICE_NAME: "promptflow",
        }
    )
    trace.set_tracer_provider(TracerProvider(resource=resource))
    provider = trace.get_tracer_provider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    data_field_name = "comment"
    feedback_data = {data_field_name: "positive"}
    response = flow_serving_client.post("/feedback?flatten=true", data=json.dumps(feedback_data))
    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes[data_field_name] == feedback_data[data_field_name]


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_feedback_with_trace_context(flow_serving_client):
    resource = Resource(
        attributes={
            SERVICE_NAME: "promptflow",
        }
    )
    trace.set_tracer_provider(TracerProvider(resource=resource))
    provider = trace.get_tracer_provider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    feedback_data = json.dumps({"feedback": "positive"})
    trace_ctx_version = "00"
    trace_ctx_trace_id = "8a3c60f7d6e2f3b4a4f2f7f3f3f3f3f3"
    trace_ctx_parent_id = "f3f3f3f3f3f3f3f3"
    trace_ctx_flags = "01"
    trace_parent = f"{trace_ctx_version}-{trace_ctx_trace_id}-{trace_ctx_parent_id}-{trace_ctx_flags}"
    response = flow_serving_client.post(
        "/feedback", headers={"traceparent": trace_parent, "baggage": "userId=alice"}, data=feedback_data
    )
    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    # validate trace context
    assert spans[0].context.trace_id == int(trace_ctx_trace_id, 16)
    assert spans[0].parent.span_id == int(trace_ctx_parent_id, 16)
    # validate feedback data
    assert feedback_data == spans[0].attributes[FEEDBACK_TRACE_FIELD_NAME]
    assert spans[0].attributes["userId"] == "alice"


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_chat_swagger(serving_client_llm_chat):
    swagger_dict = json.loads(serving_client_llm_chat.get("/swagger.json").data.decode())
    expected_swagger = {
        "components": {"securitySchemes": {"bearerAuth": {"scheme": "bearer", "type": "http"}}},
        "info": {
            "title": "Promptflow[chat_flow_with_stream_output] API",
            "version": "1.0.0",
            "x-flow-name": "chat_flow_with_stream_output",
            "x-chat-history": "chat_history",
            "x-chat-input": "question",
            "x-flow-type": "chat",
            "x-chat-output": "answer",
        },
        "openapi": "3.0.0",
        "paths": {
            "/score": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {},
                                "schema": {
                                    "properties": {
                                        "chat_history": {
                                            "type": "array",
                                            "items": {"type": "object", "additionalProperties": {}},
                                        },
                                        "question": {"type": "string", "default": "What is ChatGPT?"},
                                    },
                                    "required": ["chat_history", "question"],
                                    "type": "object",
                                },
                            }
                        },
                        "description": "promptflow input data",
                        "required": True,
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"properties": {"answer": {"type": "string"}}, "type": "object"}
                                }
                            },
                            "description": "successful operation",
                        },
                        "400": {"description": "Invalid input"},
                        "default": {"description": "unexpected error"},
                    },
                    "summary": "run promptflow: chat_flow_with_stream_output with an given input",
                }
            }
        },
        "security": [{"bearerAuth": []}],
    }
    feedback_swagger = load_feedback_swagger()
    expected_swagger["paths"]["/feedback"] = feedback_swagger
    assert swagger_dict == expected_swagger


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_user_agent(flow_serving_client):
    operation_context = OperationContext.get_instance()
    assert "test-user-agent" in operation_context.get_user_agent()
    assert "promptflow-local-serving" in operation_context.get_user_agent()


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_serving_api(flow_serving_client):
    response = flow_serving_client.get("/health")
    assert b"Healthy" in response.data
    response = flow_serving_client.get("/")
    print(response.data)
    assert response.status_code == 200
    response = flow_serving_client.post("/score", data=json.dumps({"text": "hi"}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    assert "output_prompt" in json.loads(response.data.decode())
    # Assert environment variable resolved
    assert os.environ["API_TYPE"] == "azure"


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_evaluation_flow_serving_api(evaluation_flow_serving_client):
    response = evaluation_flow_serving_client.post("/score", data=json.dumps({"url": "https://www.microsoft.com/"}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    assert "category" in json.loads(response.data.decode())


@pytest.mark.e2etest
def test_unknown_api(flow_serving_client):
    response = flow_serving_client.get("/unknown")
    assert b"not supported by current app" in response.data
    assert response.status_code == 404
    response = flow_serving_client.post("/health")  # health api should be GET
    assert b"not supported by current app" in response.data
    assert response.status_code == 404


@pytest.mark.usefixtures("recording_injection", "setup_local_connection")
@pytest.mark.e2etest
@pytest.mark.parametrize(
    "accept, expected_status_code, expected_content_type",
    [
        ("text/event-stream", 200, "text/event-stream; charset=utf-8"),
        ("text/html", 406, "application/json"),
        ("application/json", 200, "application/json"),
        ("*/*", 200, "application/json"),
        ("text/event-stream, application/json", 200, "text/event-stream; charset=utf-8"),
        ("application/json, */*", 200, "application/json"),
        ("", 200, "application/json"),
    ],
)
def test_stream_llm_chat(
    serving_client_llm_chat,
    accept,
    expected_status_code,
    expected_content_type,
):
    payload = {
        "question": "What is the capital of France?",
        "chat_history": [],
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    response = serving_client_llm_chat.post("/score", json=payload, headers=headers)
    assert response.status_code == expected_status_code
    assert response.content_type == expected_content_type

    if response.status_code == 406:
        assert response.json["error"]["code"] == "UserError"
        assert (
            f"Media type {accept} in Accept header is not acceptable. Supported media type(s) -"
            in response.json["error"]["message"]
        )

    if "text/event-stream" in response.content_type:
        for line in response.data.decode().split("\n"):
            print(line)
    else:
        result = response.json
        print(result)


@pytest.mark.e2etest
@pytest.mark.parametrize(
    "accept, expected_status_code, expected_content_type",
    [
        ("text/event-stream", 200, "text/event-stream; charset=utf-8"),
        ("text/html", 406, "application/json"),
        ("application/json", 200, "application/json"),
        ("*/*", 200, "application/json"),
        ("text/event-stream, application/json", 200, "text/event-stream; charset=utf-8"),
        ("application/json, */*", 200, "application/json"),
        ("", 200, "application/json"),
    ],
)
def test_stream_python_stream_tools(
    serving_client_python_stream_tools,
    accept,
    expected_status_code,
    expected_content_type,
):
    payload = {
        "text": "Hello World!",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    response = serving_client_python_stream_tools.post("/score", json=payload, headers=headers)
    assert response.status_code == expected_status_code
    assert response.content_type == expected_content_type

    # The predefined flow in this test case is echo flow, which will return the input text.
    # Check output as test logic validation.
    # Stream generator generating logic
    # - The output is split into words, and each word is sent as a separate event
    # - Event data is a dict { $flowoutput_field_name : $word}
    # - The event data is formatted as f"data: {json.dumps(data)}\n\n"
    # - Generator will yield the event data for each word
    if response.status_code == 200:
        expected_output = f"Echo: {payload.get('text')}"
        if "text/event-stream" in response.content_type:
            words = expected_output.split()
            lines = response.data.decode().split("\n\n")

            # The last line is empty
            lines = lines[:-1]
            assert all(f"data: {json.dumps({'output_echo': f'{w} '})}" == l for w, l in zip(words, lines))
        else:
            # For json response, iterator is joined into a string with "" as delimiter
            words = expected_output.split()
            merged_text = "".join(word + " " for word in words)
            expected_json = {"output_echo": merged_text}
            result = response.json
            assert expected_json == result
    elif response.status_code == 406:
        assert response.json["error"]["code"] == "UserError"
        assert (
            f"Media type {accept} in Accept header is not acceptable. Supported media type(s) -"
            in response.json["error"]["message"]
        )


@pytest.mark.usefixtures("recording_injection")
@pytest.mark.e2etest
@pytest.mark.parametrize(
    "accept, expected_status_code, expected_content_type",
    [
        ("text/event-stream", 406, "application/json"),
        ("application/json", 200, "application/json"),
        ("*/*", 200, "application/json"),
        ("text/event-stream, application/json", 200, "application/json"),
        ("application/json, */*", 200, "application/json"),
        ("", 200, "application/json"),
    ],
)
def test_stream_python_nonstream_tools(
    flow_serving_client,
    accept,
    expected_status_code,
    expected_content_type,
):
    payload = {
        "text": "Hello World!",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    response = flow_serving_client.post("/score", json=payload, headers=headers)
    if "text/event-stream" in response.content_type:
        for line in response.data.decode().split("\n"):
            print(line)
    else:
        result = response.json
        print(result)
    assert response.status_code == expected_status_code
    assert response.content_type == expected_content_type


@pytest.mark.usefixtures("serving_client_image_python_flow", "recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_image_flow(serving_client_image_python_flow, sample_image):
    response = serving_client_image_python_flow.post("/score", data=json.dumps({"image": sample_image}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert {"output"} == response.keys()
    key_regex = re.compile(r"data:image/(.*);base64")
    assert re.match(key_regex, list(response["output"].keys())[0])


@pytest.mark.usefixtures("serving_client_composite_image_flow", "recording_injection", "setup_local_connection")
@pytest.mark.e2etest
def test_list_image_flow(serving_client_composite_image_flow, sample_image):
    image_dict = {"data:image/jpg;base64": sample_image}
    response = serving_client_composite_image_flow.post(
        "/score", data=json.dumps({"image_list": [image_dict], "image_dict": {"my_image": image_dict}})
    )
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert {"output"} == response.keys()
    assert (
        "data:image/jpg;base64" in response["output"][0]
    ), f"data:image/jpg;base64 not in output list {response['output']}"


@pytest.mark.usefixtures("serving_client_with_environment_variables")
@pytest.mark.e2etest
def test_flow_with_environment_variables(serving_client_with_environment_variables):
    except_environment_variables = {
        "env1": "2",
        "env2": "runtime_env2",
        "env3": "[1, 2, 3, 4, 5]",
        "env4": '{"a": 1, "b": "2"}',
        "env10": "aaaaa",
    }
    for key, value in except_environment_variables.items():
        response = serving_client_with_environment_variables.post("/score", data=json.dumps({"key": key}))
        assert (
            response.status_code == 200
        ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
        response = json.loads(response.data.decode())
        assert {"output"} == response.keys()
        assert response["output"] == value


@pytest.mark.e2etest
def test_eager_flow_serve(simple_eager_flow):
    response = simple_eager_flow.post("/score", data=json.dumps({"input_val": "hi"}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert response == {"output": "Hello world! hi"}


@pytest.mark.e2etest
def test_eager_flow_swagger(simple_eager_flow):
    swagger_dict = json.loads(simple_eager_flow.get("/swagger.json").data.decode())
    expected_swagger = {
        "components": {"securitySchemes": {"bearerAuth": {"scheme": "bearer", "type": "http"}}},
        "info": {
            "title": "Promptflow[simple_with_dict_output] API",
            "version": "1.0.0",
            "x-flow-name": "simple_with_dict_output",
        },
        "openapi": "3.0.0",
        "paths": {
            "/score": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {},
                                "schema": {
                                    "properties": {"input_val": {"default": "gpt", "type": "string"}},
                                    "required": ["input_val"],
                                    "type": "object",
                                },
                            }
                        },
                        "description": "promptflow " "input data",
                        "required": True,
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "properties": {"output": {"additionalProperties": {}, "type": "object"}},
                                        "type": "object",
                                    }
                                }
                            },
                            "description": "successful " "operation",
                        },
                        "400": {"description": "Invalid " "input"},
                        "default": {"description": "unexpected " "error"},
                    },
                    "summary": "run promptflow: " "simple_with_dict_output with an " "given input",
                }
            }
        },
        "security": [{"bearerAuth": []}],
    }
    feedback_swagger = load_feedback_swagger()
    expected_swagger["paths"]["/feedback"] = feedback_swagger
    assert swagger_dict == expected_swagger


@pytest.mark.e2etest
def test_eager_flow_serve_primitive_output(simple_eager_flow_primitive_output):
    response = simple_eager_flow_primitive_output.post("/score", data=json.dumps({"input_val": "hi"}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    # response original value
    assert response == "Hello world! hi"


@pytest.mark.e2etest
def test_eager_flow_primitive_output_swagger(simple_eager_flow_primitive_output):
    swagger_dict = json.loads(simple_eager_flow_primitive_output.get("/swagger.json").data.decode())
    expected_swagger = {
        "components": {"securitySchemes": {"bearerAuth": {"scheme": "bearer", "type": "http"}}},
        "info": {"title": "Promptflow[primitive_output] API", "version": "1.0.0", "x-flow-name": "primitive_output"},
        "openapi": "3.0.0",
        "paths": {
            "/score": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {},
                                "schema": {
                                    "properties": {"input_val": {"default": "gpt", "type": "string"}},
                                    "required": ["input_val"],
                                    "type": "object",
                                },
                            }
                        },
                        "description": "promptflow " "input data",
                        "required": True,
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"properties": {"output": {"type": "string"}}, "type": "object"}
                                }
                            },
                            "description": "successful " "operation",
                        },
                        "400": {"description": "Invalid " "input"},
                        "default": {"description": "unexpected " "error"},
                    },
                    "summary": "run promptflow: primitive_output " "with an given input",
                }
            }
        },
        "security": [{"bearerAuth": []}],
    }
    feedback_swagger = load_feedback_swagger()
    expected_swagger["paths"]["/feedback"] = feedback_swagger
    assert swagger_dict == expected_swagger


@pytest.mark.e2etest
def test_eager_flow_serve_dataclass_output(simple_eager_flow_dataclass_output):
    response = simple_eager_flow_dataclass_output.post(
        "/score", data=json.dumps({"text": "my_text", "models": ["my_model"]})
    )
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    # response dict of dataclass
    assert response == {"models": ["my_model"], "text": "my_text"}


@pytest.mark.e2etest
def test_eager_flow_serve_non_json_serializable_output(non_json_serializable_output):
    response = non_json_serializable_output.post("/score", data=json.dumps({}))
    assert (
        response.status_code == 400
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert response == {
        "error": {
            "code": "UserError",
            "message": "The output 'output' for flow is incorrect. The output value is not JSON serializable. "
            "JSON dump failed: (TypeError) Object of type Output is not JSON serializable. "
            "Please verify your flow output and make sure the value serializable.",
        }
    }


@pytest.mark.e2etest
@pytest.mark.parametrize(
    "accept, expected_status_code, expected_content_type",
    [
        ("text/event-stream", 200, "text/event-stream; charset=utf-8"),
        ("text/html", 406, "application/json"),
        ("application/json", 200, "application/json"),
        ("*/*", 200, "application/json"),
        ("text/event-stream, application/json", 200, "text/event-stream; charset=utf-8"),
        ("application/json, */*", 200, "application/json"),
        ("", 200, "application/json"),
    ],
)
def test_eager_flow_stream_output(
    stream_output,
    accept,
    expected_status_code,
    expected_content_type,
):
    payload = {
        "input_val": "val",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    response = stream_output.post("/score", json=payload, headers=headers)
    error_msg = f"Response code indicates error {response.status_code} - {response.data.decode()}"
    assert response.status_code == expected_status_code, error_msg
    assert response.content_type == expected_content_type

    if response.status_code == 406:
        assert response.json["error"]["code"] == "UserError"
        assert (
            f"Media type {accept} in Accept header is not acceptable. Supported media type(s) -"
            in response.json["error"]["message"]
        )

    if "text/event-stream" in response.content_type:
        for line in response.data.decode().split("\n"):
            print(line)
    else:
        result = response.json
        print(result)


@pytest.mark.e2etest
def test_eager_flow_multiple_stream_output(multiple_stream_outputs):
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    response = multiple_stream_outputs.post("/score", data=json.dumps({"input_val": 1}), headers=headers)
    assert (
        response.status_code == 400
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert response == {"error": {"code": "UserError", "message": "Multiple stream output fields not supported."}}


@pytest.mark.e2etest
def test_eager_flow_evc(eager_flow_evc):
    # Supported: flow with EVC in definition
    response = eager_flow_evc.post("/score", data=json.dumps({}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert response == "Hello world! azure"


@pytest.mark.e2etest
def test_eager_flow_evc_override(eager_flow_evc_override):
    # Supported: EVC's connection exist in flow definition
    response = eager_flow_evc_override.post("/score", data=json.dumps({}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    assert response != "Hello world! ${azure_open_ai_connection.api_base}"


@pytest.mark.e2etest
def test_eager_flow_evc_override_not_exist(eager_flow_evc_override_not_exist):
    # EVC's connection not exist in flow definition, will resolve it.
    response = eager_flow_evc_override_not_exist.post("/score", data=json.dumps({}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    # EVC not resolved since the connection not exist in flow definition
    assert response == "Hello world! azure"


@pytest.mark.e2etest
def test_eager_flow_evc_connection_not_exist(eager_flow_evc_connection_not_exist):
    # Won't get not existed connection since it's override
    response = eager_flow_evc_connection_not_exist.post("/score", data=json.dumps({}))
    assert (
        response.status_code == 200
    ), f"Response code indicates error {response.status_code} - {response.data.decode()}"
    response = json.loads(response.data.decode())
    # EVC not resolved since the connection not exist in flow definition
    assert response == "Hello world! VALUE"


@pytest.mark.e2etest
def test_eager_flow_with_init(callable_class):
    response1 = callable_class.post("/score", data=json.dumps({"func_input": "input2"}))
    assert (
        response1.status_code == 200
    ), f"Response code indicates error {response1.status_code} - {response1.data.decode()}"
    response1 = json.loads(response1.data.decode())

    response2 = callable_class.post("/score", data=json.dumps({"func_input": "input2"}))
    assert (
        response2.status_code == 200
    ), f"Response code indicates error {response2.status_code} - {response2.data.decode()}"
    response2 = json.loads(response2.data.decode())
    assert response1 == response2
