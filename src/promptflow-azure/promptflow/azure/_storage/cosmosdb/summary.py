import datetime
import logging
import time
import typing
from dataclasses import asdict, dataclass, field

from azure.cosmos import ContainerProxy

from promptflow._constants import (
    OK_LINE_RUN_STATUS,
    RUNNING_LINE_RUN_STATUS,
    SpanAttributeFieldName,
    SpanResourceAttributesFieldName,
    SpanStatusFieldName,
)
from promptflow._sdk._constants import TRACE_DEFAULT_COLLECTION
from promptflow._sdk._utils import json_loads_parse_const_as_str
from promptflow._sdk.entities._trace import Span
from promptflow.azure._storage.cosmosdb.cosmosdb_utils import safe_create_cosmosdb_item


@dataclass
class SummaryLine:
    """
    This class represents an Item in Summary container
    """

    id: str
    partition_key: str
    session_id: str
    trace_id: str
    collection_id: str
    root_span_id: str = ""
    inputs: typing.Dict = field(default_factory=dict)
    outputs: typing.Dict = field(default_factory=dict)
    start_time: str = ""
    end_time: str = ""
    status: str = ""
    latency: float = 0.0
    name: str = ""
    kind: str = ""
    created_by: typing.Dict = field(default_factory=dict)
    cumulative_token_count: typing.Optional[typing.Dict[str, int]] = field(default_factory=dict)
    evaluations: typing.Dict = field(default_factory=dict)
    # Only for batch run
    batch_run_id: str = None
    line_number: str = None
    # Only for line run
    line_run_id: str = None


@dataclass
class LineEvaluation:
    """
    This class represents an evaluation value in Summary container item.

    """

    outputs: typing.Dict
    trace_id: str
    root_span_id: str
    name: str
    created_by: typing.Dict
    collection_id: str
    flow_id: str = None
    # Only for batch run
    batch_run_id: str = None
    line_number: str = None
    # Only for line run
    line_run_id: str = None


class Summary:
    def __init__(self, span: Span, collection_id: str, created_by: typing.Dict, logger: logging.Logger) -> None:
        self.span = span
        self.created_by = created_by
        self.logger = logger
        self.session_id = self.span.resource.get(SpanResourceAttributesFieldName.COLLECTION, TRACE_DEFAULT_COLLECTION)
        self.collection_id = collection_id

    def persist(self, client: ContainerProxy):
        if self.span.parent_id:
            # For non root span, write a placeholder item to LineSummary table.
            self._persist_running_item(client)
            return
        attributes = self.span.attributes

        # Persist root span as a line run.
        self._persist_line_run(client)

        if (
            SpanAttributeFieldName.LINE_RUN_ID not in attributes
            and SpanAttributeFieldName.BATCH_RUN_ID not in attributes
        ):
            self.logger.info(
                "No line run id or batch run id found. Could be aggregate node, eager flow or arbitrary script. "
                "Ignore for patching evaluations."
            )
            return

        if SpanAttributeFieldName.REFERENCED_LINE_RUN_ID in attributes or (
            SpanAttributeFieldName.REFERENCED_BATCH_RUN_ID in attributes
            and SpanAttributeFieldName.LINE_NUMBER in attributes
        ):
            self._insert_evaluation_with_retry(client)

    # When there is the first span for line run, write placeholder item to LineSummary table.
    def _persist_running_item(self, client: ContainerProxy):
        trace_id = self.span.trace_id
        session_id = self.session_id

        item = SummaryLine(
            id=trace_id,
            partition_key=self.collection_id,
            session_id=session_id,
            trace_id=trace_id,
            status=RUNNING_LINE_RUN_STATUS,
            collection_id=self.collection_id,
            created_by=self.created_by,
            start_time=self.span.start_time.isoformat(),
        )
        attributes: dict = self.span.attributes
        if SpanAttributeFieldName.LINE_RUN_ID in attributes:
            item.line_run_id = attributes[SpanAttributeFieldName.LINE_RUN_ID]
        elif SpanAttributeFieldName.BATCH_RUN_ID in attributes and SpanAttributeFieldName.LINE_NUMBER in attributes:
            item.batch_run_id = attributes[SpanAttributeFieldName.BATCH_RUN_ID]
            item.line_number = attributes[SpanAttributeFieldName.LINE_NUMBER]
        safe_create_cosmosdb_item(client, item)

    def _persist_line_run(self, client: ContainerProxy):
        attributes: dict = self.span.attributes

        session_id = self.session_id
        start_time = self.span.start_time.isoformat()
        end_time = self.span.end_time.isoformat()

        # Span's original format don't include latency, so we need to calculate it.
        # Convert ISO 8601 formatted strings to datetime objects
        start_time_date = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_time_date = datetime.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        latency = (end_time_date - start_time_date).total_seconds()
        # calculate `cumulative_token_count`
        completion_token_count = int(attributes.get(SpanAttributeFieldName.COMPLETION_TOKEN_COUNT, 0))
        prompt_token_count = int(attributes.get(SpanAttributeFieldName.PROMPT_TOKEN_COUNT, 0))
        total_token_count = int(attributes.get(SpanAttributeFieldName.TOTAL_TOKEN_COUNT, 0))
        # if there is no token usage, set `cumulative_token_count` to None
        if total_token_count > 0:
            cumulative_token_count = {
                "completion": completion_token_count,
                "prompt": prompt_token_count,
                "total": total_token_count,
            }
        else:
            cumulative_token_count = None
        item = SummaryLine(
            id=self.span.trace_id,  # trace id is unique for LineSummary container
            partition_key=self.collection_id,
            session_id=session_id,
            trace_id=self.span.trace_id,
            collection_id=self.collection_id,
            root_span_id=self.span.span_id,
            inputs=json_loads_parse_const_as_str(attributes.get(SpanAttributeFieldName.INPUTS, "{}")),
            outputs=json_loads_parse_const_as_str(attributes.get(SpanAttributeFieldName.OUTPUT, "{}")),
            start_time=start_time,
            end_time=end_time,
            status=self.span.status[SpanStatusFieldName.STATUS_CODE],
            latency=latency,
            name=self.span.name,
            kind=attributes[SpanAttributeFieldName.SPAN_TYPE],
            cumulative_token_count=cumulative_token_count,
            created_by=self.created_by,
        )
        if SpanAttributeFieldName.LINE_RUN_ID in attributes:
            item.line_run_id = attributes[SpanAttributeFieldName.LINE_RUN_ID]
        elif SpanAttributeFieldName.BATCH_RUN_ID in attributes and SpanAttributeFieldName.LINE_NUMBER in attributes:
            item.batch_run_id = attributes[SpanAttributeFieldName.BATCH_RUN_ID]
            item.line_number = attributes[SpanAttributeFieldName.LINE_NUMBER]

        self.logger.info(f"Persist main run for LineSummary id: {item.id}")
        # Use upsert because we may create running item in advance.
        return client.upsert_item(body=asdict(item))

    def _insert_evaluation_with_retry(self, client: ContainerProxy):
        for attempt in range(3):
            try:
                # We receive requests to persist main flow first and then evaluation,
                # but init cosmosDB client could be time consuming, and the later request will reuse the same client,
                # so it's possible that the main run is not persisted when we start to patch evaluation to it.
                self._insert_evaluation(client)
                break
            except InsertEvaluationsRetriableException as e:
                if attempt == 2:  # If this is the last attempt, ignore and just return
                    self.logger.error(f"Error while inserting evaluation: {e}")
                    return
                time.sleep(1)

    def _insert_evaluation(self, client: ContainerProxy):
        attributes: dict = self.span.attributes
        item = LineEvaluation(
            trace_id=self.span.trace_id,
            root_span_id=self.span.span_id,
            collection_id=self.collection_id,
            outputs=json_loads_parse_const_as_str(attributes.get(SpanAttributeFieldName.OUTPUT, "{}")),
            name=self.span.name,
            created_by=self.created_by,
        )

        # None is the default value for the field.
        referenced_line_run_id = attributes.get(SpanAttributeFieldName.REFERENCED_LINE_RUN_ID, None)
        referenced_batch_run_id = attributes.get(SpanAttributeFieldName.REFERENCED_BATCH_RUN_ID, None)
        line_number = attributes.get(SpanAttributeFieldName.LINE_NUMBER, None)

        query = (
            "SELECT * FROM c WHERE "
            "c.line_run_id = @line_run_id AND c.batch_run_id = @batch_run_id AND c.line_number = @line_number"
        )
        parameters = [
            {"name": "@line_run_id", "value": referenced_line_run_id},
            {"name": "@batch_run_id", "value": referenced_batch_run_id},
            {"name": "@line_number", "value": line_number},
        ]
        # Don't use partition key for query, we can't know the partition key of main run in all scenarios.
        query_results = list(client.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))

        if query_results:
            current_status = query_results[0].get("status", "")
            if current_status != OK_LINE_RUN_STATUS:
                raise InsertEvaluationsRetriableException(
                    f"Main run status is {current_status}, cannot patch evaluation now."
                )
            main_id = query_results[0]["id"]
            main_partition_key = query_results[0]["partition_key"]
        else:
            raise InsertEvaluationsRetriableException(f"Cannot find main run by parameter {parameters}.")

        if SpanAttributeFieldName.LINE_RUN_ID in attributes:
            item.line_run_id = attributes[SpanAttributeFieldName.LINE_RUN_ID]
            key = self.span.name
        else:
            batch_run_id = attributes[SpanAttributeFieldName.BATCH_RUN_ID]
            item.batch_run_id = batch_run_id
            item.line_number = line_number
            # Use the batch run id, instead of the name, as the key in the evaluations dictionary.
            # Customers may execute the same evaluation flow multiple times for a batch run.
            # We should be able to save all evaluations, as customers use batch runs in a critical manner.
            key = batch_run_id

        patch_operations = [{"op": "add", "path": f"/evaluations/{key}", "value": asdict(item)}]
        self.logger.info(f"Insert evaluation for LineSummary main_id: {main_id}")
        return client.patch_item(item=main_id, partition_key=main_partition_key, patch_operations=patch_operations)


class InsertEvaluationsRetriableException(Exception):
    pass
