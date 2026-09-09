"""Desktop processing presets and independently validated export choices."""
from dataclasses import dataclass, replace
from emailtools.models import ProcessingOptions, AnalysisResult

MODE_NAMES = {"list": "메일 목록만", "archive": "목록과 첨부 정리", "analyze": "목록·첨부·표 분석"}


def options_for_mode(mode: str) -> ProcessingOptions:
    if mode not in MODE_NAMES:
        raise ValueError("알 수 없는 작업입니다.")
    return ProcessingOptions(mail_index=True, attachment_index=mode != "list",
        save_attachments=mode != "list", extract_tables=mode == "analyze")


@dataclass(frozen=True)
class ExportPlan:
    attachments: bool = False
    attachment_index: bool = False
    body: bool = False
    text: bool = False
    tables: bool = False
    archive: bool = True

    @classmethod
    def from_options(cls, options: ProcessingOptions):
        return cls(options.save_attachments, options.attachment_index, options.save_mail,
                   options.extract_text, options.extract_tables)

    def apply(self, result: AnalysisResult) -> AnalysisResult:
        for wanted, prepared in ((self.attachments, result.options.save_attachments),
                (self.body, result.options.save_mail), (self.text, result.options.extract_text),
                (self.tables, result.options.extract_tables)):
            if wanted and not prepared:
                raise ValueError("추가 처리가 필요합니다. 작업 설정에서 다시 분석해 주세요.")
        return replace(result, options=replace(result.options, mail_index=True,
            save_attachments=self.attachments, attachment_index=self.attachment_index,
            save_mail=self.body, extract_text=self.text, extract_tables=self.tables))
