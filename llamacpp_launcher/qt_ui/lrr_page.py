from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..glossaries import GlossaryService
from ..models import AppSettings, Glossary, GlossaryEntry, ValidationError
from ..storage import SettingsStore
from .components import (
    ModernSpinBox,
    NameDialog,
    SmoothSwitch,
    card,
    make_button,
    section_header,
)
from .presentation import clone_settings, endpoint_text


class GlossaryEntryRow(QWidget):
    remove_requested = pyqtSignal(object)

    def __init__(
        self, entry: GlossaryEntry | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.entry_id = entry.id if entry else ""
        self.case_sensitive = entry.case_sensitive if entry else True
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        self.enabled = SmoothSwitch(accessible_name="Enable glossary entry")
        self.enabled.setChecked(entry.enabled if entry else True)
        self.source = QLineEdit(entry.source if entry else "")
        self.source.setPlaceholderText("Source text")
        self.source.setAccessibleName("Glossary source")
        self.replacement = QLineEdit(entry.replacement if entry else "")
        self.replacement.setPlaceholderText("Replacement")
        self.replacement.setAccessibleName("Glossary replacement")
        self.remove = make_button("Remove", danger=True, accessible_name="Remove glossary entry")
        self.remove.clicked.connect(
            lambda _checked=False: self.remove_requested.emit(self)
        )
        layout.addWidget(self.enabled)
        layout.addWidget(self.source, 1)
        layout.addWidget(self.replacement, 1)
        layout.addWidget(self.remove)
        self.setMaximumHeight(48)

    def to_entry(self) -> GlossaryEntry:
        kwargs = {
            "source": self.source.text(),
            "replacement": self.replacement.text(),
            "enabled": self.enabled.isChecked(),
            "case_sensitive": self.case_sensitive,
        }
        if self.entry_id:
            kwargs["id"] = self.entry_id
        return GlossaryEntry(**kwargs)


class LrrPage(QWidget):
    message = pyqtSignal(str)
    error = pyqtSignal(str)
    settings_changed = pyqtSignal()

    def __init__(
        self,
        settings: AppSettings,
        store: SettingsStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self.glossaries = GlossaryService(settings)
        self.current_glossary_id = ""
        self.rows: list[GlossaryEntryRow] = []
        self._loading = False
        self._dirty = False
        self._build()
        self.restore()

    def _build(self) -> None:
        page_layout = QHBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(14)

        rail, rail_layout = card()
        rail.setFixedWidth(210)
        rail_layout.addWidget(
            section_header("Glossaries", "Saved LRR replacement sets")
        )
        self.glossary_list = QListWidget()
        self.glossary_list.setAccessibleName("Saved glossaries")
        rail_layout.addWidget(self.glossary_list, 1)
        rail_actions = QHBoxLayout()
        self.new_button = make_button("+ New")
        self.rename_button = make_button("Rename")
        rail_actions.addWidget(self.new_button)
        rail_actions.addWidget(self.rename_button)
        rail_layout.addLayout(rail_actions)
        self.delete_button = make_button("Delete", danger=True)
        rail_layout.addWidget(self.delete_button)
        page_layout.addWidget(rail)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 2, 8, 8)
        layout.setSpacing(14)
        scroll.setWidget(body)

        heading = QLabel("LRR")
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        settings_card, settings_layout = card()
        header = QHBoxLayout()
        header.addWidget(
            section_header(
                "Response relay",
                "OpenAI-compatible client endpoint with glossary replacement.",
            ),
            1,
        )
        self.enabled = SmoothSwitch(accessible_name="Enable LRR")
        header.addWidget(self.enabled)
        header.addWidget(QLabel("Enable LRR"))
        settings_layout.addLayout(header)
        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(QLabel("Listen host"))
        self.host = QLineEdit()
        endpoint_row.addWidget(self.host, 1)
        endpoint_row.addWidget(QLabel("Port"))
        self.port = ModernSpinBox()
        self.port.setRange(1, 65535)
        endpoint_row.addWidget(self.port)
        self.save_lrr_button = make_button("Save LRR", primary=True)
        endpoint_row.addWidget(self.save_lrr_button)
        settings_layout.addLayout(endpoint_row)
        self.client_endpoint = QLabel()
        self.client_endpoint.setProperty("role", "muted")
        settings_layout.addWidget(self.client_endpoint)
        layout.addWidget(settings_card)

        glossary_card, glossary_layout = card()
        entries_header = QHBoxLayout()
        self.glossary_heading = QLabel("Select a glossary")
        self.glossary_heading.setProperty("role", "section")
        entries_header.addWidget(self.glossary_heading)
        entries_header.addStretch()
        self.add_button = make_button("+ Add entry")
        entries_header.addWidget(self.add_button)
        glossary_layout.addLayout(entries_header)
        self.entries_scroll = QScrollArea()
        self.entries_scroll.setWidgetResizable(True)
        self.entries_scroll.setMinimumHeight(190)
        self.entries_body = QWidget()
        self.entries_layout = QVBoxLayout(self.entries_body)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        self.entries_layout.setSpacing(4)
        self.entries_layout.addStretch()
        self.entries_scroll.setWidget(self.entries_body)
        glossary_layout.addWidget(self.entries_scroll)
        bottom = QHBoxLayout()
        self.glossary_error = QLabel()
        self.glossary_error.setProperty("role", "error")
        self.glossary_error.setWordWrap(True)
        bottom.addWidget(self.glossary_error, 1)
        self.save_glossary_button = make_button("Save glossary", primary=True)
        bottom.addWidget(self.save_glossary_button)
        glossary_layout.addLayout(bottom)
        layout.addWidget(glossary_card)
        layout.addStretch()
        page_layout.addWidget(scroll, 1)

        self.enabled.toggled.connect(self._update_endpoint)
        self.host.textChanged.connect(self._update_endpoint)
        self.port.valueChanged.connect(self._update_endpoint)
        self.save_lrr_button.clicked.connect(
            lambda _checked=False: self.save_lrr()
        )
        self.glossary_list.currentItemChanged.connect(self._selected)
        self.new_button.clicked.connect(
            lambda _checked=False: self.new_glossary()
        )
        self.rename_button.clicked.connect(
            lambda _checked=False: self.rename_glossary()
        )
        self.delete_button.clicked.connect(
            lambda _checked=False: self.delete_glossary()
        )
        self.add_button.clicked.connect(
            lambda _checked=False: self.add_entry()
        )
        self.save_glossary_button.clicked.connect(
            lambda _checked=False: self.save_glossary()
        )
        self._update_glossary_actions()

    def restore(self) -> None:
        self.enabled.setChecked(self.settings.interceptor_enabled)
        self.host.setText(self.settings.interceptor_host)
        self.port.setValue(self.settings.interceptor_port)
        self.refresh_glossaries(select=self.settings.selected_glossary_id)
        if self.settings.selected_glossary_id:
            self.load_glossary(self.settings.selected_glossary_id)
        else:
            self.render_entries([])
        self._update_endpoint()

    def _update_endpoint(self) -> None:
        self.client_endpoint.setText(
            "Client endpoint: "
            + endpoint_text(
                self.host.text(), self.port.value(), enabled=self.enabled.isChecked()
            )
        )

    def save_lrr(self) -> bool:
        snapshot = clone_settings(self.settings)
        try:
            self.settings.interceptor_enabled = self.enabled.isChecked()
            self.settings.interceptor_host = self.host.text().strip()
            self.settings.interceptor_port = self.port.value()
            self.store.save(self.settings)
        except ValidationError as exc:
            _restore_settings(self.settings, snapshot)
            self._show_error(str(exc), self.host)
            return False
        self.message.emit("LRR settings saved.")
        self.settings_changed.emit()
        return True

    def refresh_glossaries(self, *, select: str = "") -> None:
        self._loading = True
        self.glossary_list.clear()
        for glossary in self.settings.glossaries:
            item = QListWidgetItem(glossary.name)
            item.setData(Qt.ItemDataRole.UserRole, glossary.id)
            self.glossary_list.addItem(item)
        target = select or self.settings.selected_glossary_id
        for index in range(self.glossary_list.count()):
            item = self.glossary_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == target:
                self.glossary_list.setCurrentItem(item)
                break
        self._loading = False
        self._update_glossary_actions()

    def _selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self._loading:
            return
        glossary_id = (
            str(current.data(Qt.ItemDataRole.UserRole) or "")
            if current is not None
            else ""
        )
        if self._dirty and self.current_glossary_id != glossary_id:
            if not self.save_glossary(announce=False, reload_editor=False):
                self._reselect_current()
                return
        snapshot = clone_settings(self.settings)
        self.settings.selected_glossary_id = glossary_id
        try:
            self.store.save(self.settings)
        except ValidationError as exc:
            _restore_settings(self.settings, snapshot)
            self.glossaries = GlossaryService(self.settings)
            self._show_error(str(exc))
            self._reselect_current()
            return
        if glossary_id:
            self.load_glossary(glossary_id)
        else:
            self.current_glossary_id = ""
            self.render_entries([])
            self.glossary_heading.setText("Select a glossary")
        self._update_glossary_actions()
        self.settings_changed.emit()

    def load_glossary(self, glossary_id: str) -> None:
        glossary = self.glossaries.get(glossary_id)
        self.current_glossary_id = glossary.id
        self.glossary_heading.setText(glossary.name)
        self.render_entries(glossary.entries)
        self._dirty = False
        self._update_glossary_actions()

    def new_glossary(self, name: str | None = None) -> None:
        if name is None:
            dialog = NameDialog("New glossary", "Glossary name", parent=self)
            if not dialog.exec():
                return
            name = dialog.value
        snapshot = clone_settings(self.settings)
        try:
            glossary = self.glossaries.create(Glossary(name=name))
            self.store.save(self.settings)
        except ValidationError as exc:
            _restore_settings(self.settings, snapshot)
            self.glossaries = GlossaryService(self.settings)
            self._show_error(str(exc))
            return
        self.refresh_glossaries(select=glossary.id)
        self.load_glossary(glossary.id)
        self.add_entry()
        self.message.emit(f'Created glossary "{glossary.name}".')
        self.settings_changed.emit()

    def rename_glossary(self, name: str | None = None) -> None:
        if not self.current_glossary_id:
            return
        existing = self.glossaries.get(self.current_glossary_id)
        if name is None:
            dialog = NameDialog(
                "Rename glossary", "New glossary name", existing.name, self
            )
            if not dialog.exec():
                return
            name = dialog.value
        snapshot = clone_settings(self.settings)
        try:
            updated = self.glossaries.rename(existing.id, name)
            self.store.save(self.settings)
        except ValidationError as exc:
            _restore_settings(self.settings, snapshot)
            self.glossaries = GlossaryService(self.settings)
            self._show_error(str(exc))
            return
        self.refresh_glossaries(select=updated.id)
        self.load_glossary(updated.id)
        self.message.emit(f'Renamed glossary to "{updated.name}".')
        self.settings_changed.emit()

    def delete_glossary(self, *, confirm: bool = True) -> None:
        if not self.current_glossary_id:
            return
        glossary = self.glossaries.get(self.current_glossary_id)
        if confirm and QMessageBox.question(
            self, "Delete glossary", f'Delete glossary "{glossary.name}"?'
        ) is not QMessageBox.StandardButton.Yes:
            return
        snapshot = clone_settings(self.settings)
        try:
            self.glossaries.delete(glossary.id)
            self.store.save(self.settings)
        except ValidationError as exc:
            _restore_settings(self.settings, snapshot)
            self.glossaries = GlossaryService(self.settings)
            self._show_error(str(exc))
            return
        self.refresh_glossaries(select=self.settings.selected_glossary_id)
        if self.settings.selected_glossary_id:
            self.load_glossary(self.settings.selected_glossary_id)
        else:
            self.current_glossary_id = ""
            self.render_entries([])
        self.message.emit("Glossary deleted.")
        self.settings_changed.emit()

    def add_entry(self, entry: GlossaryEntry | None = None) -> GlossaryEntryRow:
        row = GlossaryEntryRow(entry)
        row.remove_requested.connect(self.remove_entry)
        row.enabled.toggled.connect(self._mark_dirty)
        row.source.textChanged.connect(self._mark_dirty)
        row.replacement.textChanged.connect(self._mark_dirty)
        self.rows.append(row)
        self.entries_layout.insertWidget(self.entries_layout.count() - 1, row)
        row.source.setFocus()
        if entry is None:
            self._dirty = True
        return row

    def remove_entry(self, row: GlossaryEntryRow) -> None:
        if row in self.rows:
            self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self._dirty = True

    def render_entries(self, entries: list[GlossaryEntry]) -> None:
        self._loading = True
        for row in self.rows:
            row.setParent(None)
            row.deleteLater()
        self.rows.clear()
        for entry in entries:
            self.add_entry(entry)
        self._loading = False
        self._dirty = False

    def glossary_from_form(self) -> Glossary:
        if not self.current_glossary_id:
            raise ValidationError("Create or select a glossary first.")
        existing = self.glossaries.get(self.current_glossary_id)
        glossary = Glossary(
            id=existing.id,
            name=existing.name,
            entries=[
                row.to_entry()
                for row in self.rows
                if row.source.text().strip()
                or row.replacement.text().strip()
            ],
        )
        glossary.validate()
        return glossary

    def save_glossary(
        self,
        *,
        announce: bool = True,
        reload_editor: bool = True,
    ) -> bool:
        snapshot = clone_settings(self.settings)
        try:
            glossary = self.glossary_from_form()
            self.glossaries.update(glossary.id, glossary)
            self.store.save(self.settings)
        except ValidationError as exc:
            _restore_settings(self.settings, snapshot)
            self.glossaries = GlossaryService(self.settings)
            self._show_error(str(exc), self.rows[0].source if self.rows else None)
            return False
        self.glossary_error.clear()
        if reload_editor:
            self.load_glossary(glossary.id)
        self._dirty = False
        if announce:
            self.message.emit(f'Saved glossary "{glossary.name}".')
        self.settings_changed.emit()
        return True

    def _show_error(self, message: str, widget: QWidget | None = None) -> None:
        self.glossary_error.setText(message)
        self.error.emit(message)
        if widget is not None:
            widget.setAccessibleDescription(message)
            widget.setFocus()

    def _mark_dirty(self, *_args: object) -> None:
        if not self._loading:
            self._dirty = True

    def _reselect_current(self) -> None:
        self._loading = True
        self.glossary_list.clearSelection()
        for index in range(self.glossary_list.count()):
            item = self.glossary_list.item(index)
            if (
                item.data(Qt.ItemDataRole.UserRole)
                == self.current_glossary_id
            ):
                self.glossary_list.setCurrentItem(item)
                break
        self._loading = False

    def _update_glossary_actions(self) -> None:
        has_glossary = bool(self.current_glossary_id)
        self.rename_button.setEnabled(has_glossary)
        self.delete_button.setEnabled(has_glossary)
        self.add_button.setEnabled(has_glossary)
        self.save_glossary_button.setEnabled(has_glossary)


def _restore_settings(target: AppSettings, source: AppSettings) -> None:
    for field in source.__dataclass_fields__:
        setattr(target, field, getattr(source, field))
