from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import AppSettings, FlashAttention, GpuMode, Profile, ValidationError
from ..profiles import ProfileService
from ..storage import SettingsStore
from .components import (
    ModernComboBox,
    ModernSpinBox,
    NameDialog,
    PathRow,
    SmoothSwitch,
    card,
    make_button,
    section_header,
)
from .presentation import clone_settings, context_per_slot_text, profile_from_values


class SettingsPage(QWidget):
    discover_requested = pyqtSignal(str)
    message = pyqtSignal(str)
    error = pyqtSignal(str)
    selection_changed = pyqtSignal()

    def __init__(
        self,
        settings: AppSettings,
        store: SettingsStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.store = store
        self.profiles = ProfileService(settings)
        self.original_profile_name = ""
        self._draft_profile_name = ""
        self.model_paths: dict[str, Path] = {}
        self._loading = False
        self._dirty = False
        self._build()
        self.refresh_profiles(select=settings.selected_profile)
        if settings.selected_profile:
            self.load_profile(settings.selected_profile)
        else:
            self.clear_form()

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        rail, rail_layout = card()
        rail.setFixedWidth(210)
        rail_layout.addWidget(section_header("Profiles", "Saved llama.cpp launch setups"))
        self.profile_list = QListWidget()
        self.profile_list.setAccessibleName("Saved profiles")
        rail_layout.addWidget(self.profile_list, 1)
        row = QHBoxLayout()
        self.new_button = make_button("+ New", primary=True)
        self.rename_button = make_button("Rename")
        row.addWidget(self.new_button)
        row.addWidget(self.rename_button)
        rail_layout.addLayout(row)
        row2 = QHBoxLayout()
        self.copy_button = make_button("Copy")
        self.delete_button = make_button("Delete", danger=True)
        row2.addWidget(self.copy_button)
        row2.addWidget(self.delete_button)
        rail_layout.addLayout(row2)
        root.addWidget(rail)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(2, 2, 8, 8)
        self.body_layout.setSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        title_row = QHBoxLayout()
        self.heading = QLabel("New Profile")
        self.heading.setProperty("role", "title")
        title_row.addWidget(self.heading)
        title_row.addStretch()
        self.save_button = make_button("Save profile", primary=True)
        title_row.addWidget(self.save_button)
        self.body_layout.addLayout(title_row)

        source_card, source_layout = card()
        source_layout.addWidget(
            section_header("Sources", "Choose the llama.cpp build and model directory.")
        )
        source_form = QFormLayout()
        source_form.setSpacing(10)
        self.llama_path = PathRow("llama.cpp folder")
        self.llama_path.edit.setText(self.settings.llama_cpp_folder)
        source_form.addRow("llama.cpp", self.llama_path)
        self.model_folder = PathRow("Models folder")
        self.model_folder.edit.setText(self.settings.model_folder)
        source_form.addRow("Models", self.model_folder)
        model_row = QHBoxLayout()
        self.model_combo = ModernComboBox()
        self.model_combo.setAccessibleName("GGUF model")
        self.refresh_button = make_button("Refresh", accessible_name="Refresh models")
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(self.refresh_button)
        model_holder = QWidget()
        model_holder.setLayout(model_row)
        source_form.addRow("Model", model_holder)
        source_layout.addLayout(source_form)
        self.body_layout.addWidget(source_card)

        params_card, params_layout = card()
        params_layout.addWidget(
            section_header("Server configuration", "Managed llama-server arguments.")
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.setAccessibleName("Profile name")
        self.host_edit = QLineEdit("127.0.0.1")
        self.port_spin = _spin(1, 65535, 8080)
        self.ngl_spin = _spin(0, 999, 0)
        self.context_spin = _spin(1, 16_777_216, 4096)
        self.parallel_spin = _spin(1, 1024, 1)
        self.flash_combo = ModernComboBox()
        self.flash_combo.addItems([item.value for item in FlashAttention])
        self.gpu_combo = ModernComboBox()
        self.gpu_combo.addItems([item.value for item in GpuMode])
        self.no_mmap = SmoothSwitch(accessible_name="Disable mmap")
        for row, (label, widget) in enumerate(
            [
                ("Profile name", self.name_edit),
                ("--host", self.host_edit),
                ("--port", self.port_spin),
                ("-ngl", self.ngl_spin),
                ("-c Context", self.context_spin),
                ("-np Parallel", self.parallel_spin),
                ("-fa", self.flash_combo),
                ("GPU mode", self.gpu_combo),
            ]
        ):
            column = 0 if row < 4 else 2
            local_row = row if row < 4 else row - 4
            grid.addWidget(QLabel(label), local_row, column)
            grid.addWidget(widget, local_row, column + 1)
        params_layout.addLayout(grid)
        self.context_hint = QLabel()
        self.context_hint.setProperty("role", "muted")
        params_layout.addWidget(self.context_hint)
        mmap_row = QHBoxLayout()
        mmap_row.addWidget(self.no_mmap)
        mmap_row.addWidget(QLabel("Disable mmap"))
        mmap_row.addStretch()
        params_layout.addLayout(mmap_row)
        params_layout.addWidget(QLabel("Custom arguments"))
        self.custom_args = QPlainTextEdit()
        self.custom_args.setMaximumHeight(78)
        self.custom_args.setPlaceholderText("--threads 8")
        params_layout.addWidget(self.custom_args)
        self.validation_label = QLabel()
        self.validation_label.setProperty("role", "error")
        self.validation_label.setWordWrap(True)
        params_layout.addWidget(self.validation_label)
        self.body_layout.addWidget(params_card)
        self.body_layout.addStretch()

        self.profile_list.currentTextChanged.connect(self._selected)
        self.new_button.clicked.connect(lambda _checked=False: self.new_profile())
        self.rename_button.clicked.connect(lambda _checked=False: self.rename_profile())
        self.copy_button.clicked.connect(lambda _checked=False: self.copy_profile())
        self.delete_button.clicked.connect(lambda _checked=False: self.delete_profile())
        self.save_button.clicked.connect(lambda _checked=False: self.save_profile())
        self.llama_path.browse_requested.connect(self.choose_llama_folder)
        self.model_folder.browse_requested.connect(self.choose_model_folder)
        self.refresh_button.clicked.connect(lambda _checked=False: self.request_models())
        self.context_spin.valueChanged.connect(self.update_context_hint)
        self.parallel_spin.valueChanged.connect(self.update_context_hint)
        for edit in (
            self.name_edit,
            self.host_edit,
            self.llama_path.edit,
            self.model_folder.edit,
        ):
            edit.textChanged.connect(self._mark_dirty)
        for spin in (
            self.port_spin,
            self.ngl_spin,
            self.context_spin,
            self.parallel_spin,
        ):
            spin.valueChanged.connect(self._mark_dirty)
        for combo in (self.model_combo, self.flash_combo, self.gpu_combo):
            combo.currentIndexChanged.connect(self._mark_dirty)
        self.no_mmap.toggled.connect(self._mark_dirty)
        self.custom_args.textChanged.connect(self._mark_dirty)
        self.update_context_hint()

    def refresh_profiles(self, *, select: str = "") -> None:
        self._loading = True
        self.profile_list.clear()
        self.profile_list.addItems(self.profiles.names())
        if self._draft_profile_name and not any(
            name.casefold() == self._draft_profile_name.casefold()
            for name in self.profiles.names()
        ):
            self.profile_list.addItem(self._draft_profile_name)
        target = select or self.settings.selected_profile
        matches = (
            self.profile_list.findItems(target, Qt.MatchFlag.MatchExactly)
            if target
            else []
        )
        if matches:
            self.profile_list.setCurrentItem(matches[0])
        self._loading = False

    def _selected(self, name: str) -> None:
        if self._loading or not name:
            return
        current_name = (
            self.original_profile_name or self._draft_profile_name
        )
        if (
            self._draft_profile_name
            and name.casefold() == self._draft_profile_name.casefold()
        ):
            return
        if (
            self._dirty
            and current_name
            and name.casefold() != current_name.casefold()
        ):
            choice = QMessageBox.question(
                self,
                "Unsaved profile",
                f'Save changes to "{current_name}" before switching?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if choice is QMessageBox.StandardButton.Cancel:
                self._reselect(current_name)
                return
            if choice is QMessageBox.StandardButton.Yes and not self.save_profile():
                self._reselect(current_name)
                return
        if self._draft_profile_name:
            self._discard_draft_item()
        self.load_profile(name)
        self.selection_changed.emit()

    def load_profile(self, name: str) -> None:
        self._loading = True
        profile = self.profiles.select(name)
        self.original_profile_name = profile.name
        self.heading.setText(profile.name)
        self.name_edit.setText(profile.name)
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        self.ngl_spin.setValue(profile.ngl)
        self.context_spin.setValue(profile.context_size)
        self.parallel_spin.setValue(profile.parallel_slots)
        self.flash_combo.setCurrentText(profile.flash_attention.value)
        self.gpu_combo.setCurrentText(profile.gpu_mode.value)
        self.no_mmap.setChecked(profile.no_mmap)
        self.custom_args.setPlainText(profile.custom_args)
        self.apply_models(list(self.model_paths.values()), selected=profile.model_path)
        self.update_context_hint()
        self._dirty = False
        self._loading = False

    def clear_form(self, name: str = "") -> None:
        self._loading = True
        self.original_profile_name = ""
        self.heading.setText(name or "New Profile")
        self.name_edit.setText(name)
        self.host_edit.setText("127.0.0.1")
        self.port_spin.setValue(8080)
        self.ngl_spin.setValue(0)
        self.context_spin.setValue(4096)
        self.parallel_spin.setValue(1)
        self.flash_combo.setCurrentText(FlashAttention.AUTO.value)
        self.gpu_combo.setCurrentText(GpuMode.AUTO.value)
        self.no_mmap.setChecked(False)
        self.custom_args.clear()
        self.validation_label.clear()
        self._loading = False
        self._dirty = bool(name)

    def new_profile(self, name: str | None = None) -> None:
        if name is None:
            dialog = NameDialog("New profile", "Profile name", parent=self)
            if not dialog.exec():
                return
            name = dialog.value
        if any(existing.casefold() == name.casefold() for existing in self.profiles.names()):
            self._validation_error(f'Profile name "{name}" is already in use.', self.name_edit)
            return
        if self._draft_profile_name:
            self._discard_draft_item()
        self._draft_profile_name = name
        self.clear_form(name)
        self._loading = True
        self.profile_list.addItem(name)
        self.profile_list.setCurrentRow(self.profile_list.count() - 1)
        self._loading = False
        self.name_edit.setFocus()

    def rename_profile(self, name: str | None = None) -> None:
        current_name = self.original_profile_name or self._draft_profile_name
        if not current_name:
            return
        if name is None:
            dialog = NameDialog(
                "Rename profile",
                "New profile name",
                current_name,
                self,
            )
            if not dialog.exec():
                return
            name = dialog.value
        if self._draft_profile_name:
            if any(
                existing.casefold() == name.casefold()
                for existing in self.profiles.names()
            ):
                self._validation_error(
                    f'Profile name "{name}" is already in use.',
                    self.name_edit,
                )
                return
            self._draft_profile_name = name
            self.heading.setText(name)
            self.name_edit.setText(name)
            current = self.profile_list.currentItem()
            if current is not None:
                current.setText(name)
            return
        self.name_edit.setText(name)
        self.save_profile()

    def copy_profile(self) -> None:
        if not self.original_profile_name:
            return
        snapshot = clone_settings(self.settings)
        try:
            copied = self.profiles.duplicate(self.original_profile_name)
            self.store.save(self.settings)
        except ValidationError as exc:
            self._restore(snapshot)
            self._validation_error(str(exc))
            return
        self.refresh_profiles(select=copied.name)
        self.load_profile(copied.name)
        self.message.emit(f'Copied profile as "{copied.name}".')

    def delete_profile(self, *, confirm: bool = True, running_profile: str = "") -> None:
        if self._draft_profile_name:
            if confirm and QMessageBox.question(
                self,
                "Delete profile",
                f'Delete profile draft "{self._draft_profile_name}"?',
            ) is not QMessageBox.StandardButton.Yes:
                return
            self._discard_draft_item()
            self.refresh_profiles(select=self.settings.selected_profile)
            if self.settings.selected_profile:
                self.load_profile(self.settings.selected_profile)
            else:
                self.clear_form()
            self.message.emit("Profile draft deleted.")
            return
        if not self.original_profile_name:
            return
        if confirm and QMessageBox.question(
            self,
            "Delete profile",
            f'Delete profile "{self.original_profile_name}"?',
        ) is not QMessageBox.StandardButton.Yes:
            return
        snapshot = clone_settings(self.settings)
        try:
            self.profiles.delete(
                self.original_profile_name, running_profile=running_profile or None
            )
            self.store.save(self.settings)
        except ValidationError as exc:
            self._restore(snapshot)
            self._validation_error(str(exc))
            return
        self.refresh_profiles(select=self.settings.selected_profile)
        if self.settings.selected_profile:
            self.load_profile(self.settings.selected_profile)
        else:
            self.clear_form()
        self.message.emit("Profile deleted.")

    def profile_from_form(self) -> Profile:
        model_path = self.model_combo.currentData()
        if not model_path:
            model_path = self.model_combo.currentText()
        return profile_from_values(
            name=self.name_edit.text(),
            model_path=str(model_path or ""),
            host=self.host_edit.text(),
            port=self.port_spin.value(),
            ngl=self.ngl_spin.value(),
            context_size=self.context_spin.value(),
            parallel_slots=self.parallel_spin.value(),
            flash_attention=self.flash_combo.currentText(),
            no_mmap=self.no_mmap.isChecked(),
            gpu_mode=self.gpu_combo.currentText(),
            custom_args=self.custom_args.toPlainText(),
        )

    def save_profile(self) -> bool:
        snapshot = clone_settings(self.settings)
        try:
            self.settings.llama_cpp_folder = self.llama_path.edit.text().strip()
            self.settings.model_folder = self.model_folder.edit.text().strip()
            profile = self.profile_from_form()
            if self.original_profile_name:
                self.profiles.update(self.original_profile_name, profile)
            else:
                self.profiles.create(profile)
            self.store.save(self.settings)
        except ValidationError as exc:
            self._restore(snapshot)
            self._validation_error(str(exc))
            return False
        self.original_profile_name = profile.name
        self._draft_profile_name = ""
        self._dirty = False
        self.validation_label.clear()
        self.refresh_profiles(select=profile.name)
        self.heading.setText(profile.name)
        self.message.emit(f'Saved profile "{profile.name}".')
        self.selection_changed.emit()
        return True

    def choose_llama_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose llama.cpp folder", self.llama_path.edit.text()
        )
        if path:
            self.llama_path.edit.setText(path)

    def choose_model_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose model folder", self.model_folder.edit.text()
        )
        if path:
            self.model_folder.edit.setText(path)
            self.request_models()

    def request_models(self) -> None:
        folder = self.model_folder.edit.text().strip()
        if not folder:
            self._validation_error("Choose a model folder first.", self.model_folder.edit)
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Scanning…")
        self.discover_requested.emit(folder)

    def apply_models(
        self, paths: list[Path], *, selected: str | None = None
    ) -> None:
        current = selected or str(self.model_combo.currentData() or "")
        self.model_paths = {path.name: path for path in paths}
        self.model_combo.clear()
        for path in paths:
            self.model_combo.addItem(path.name, str(path))
        if current:
            index = self.model_combo.findData(current)
            if index < 0:
                self.model_combo.addItem(Path(current).name or current, current)
                index = self.model_combo.count() - 1
            self.model_combo.setCurrentIndex(index)
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Refresh")

    def discovery_failed(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Refresh")
        self._validation_error(message, self.model_folder.edit)

    def update_context_hint(self) -> None:
        text = context_per_slot_text(
            self.context_spin.value(), self.parallel_spin.value()
        )
        self.context_hint.setText(text)
        self.context_hint.setVisible(bool(text))

    def _validation_error(self, message: str, widget: QWidget | None = None) -> None:
        self.validation_label.setText(message)
        self.error.emit(message)
        if widget is not None:
            widget.setProperty("invalid", True)
            widget.setAccessibleDescription(message)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.setFocus()

    def _mark_dirty(self, *_args: object) -> None:
        if not self._loading:
            self._dirty = True

    def _reselect(self, name: str) -> None:
        matches = self.profile_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if not matches:
            return
        self._loading = True
        self.profile_list.setCurrentItem(matches[0])
        self._loading = False

    def _discard_draft_item(self) -> None:
        draft_name = self._draft_profile_name
        if not draft_name:
            return
        for index in range(self.profile_list.count()):
            if self.profile_list.item(index).text().casefold() == draft_name.casefold():
                self.profile_list.takeItem(index)
                break
        self._draft_profile_name = ""

    def _restore(self, snapshot: AppSettings) -> None:
        self.settings.__dict__.update(snapshot.__dict__) if hasattr(self.settings, "__dict__") else _copy_slots(self.settings, snapshot)
        self.profiles = ProfileService(self.settings)


def _spin(minimum: int, maximum: int, value: int) -> ModernSpinBox:
    spin = ModernSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    spin.setGroupSeparatorShown(True)
    return spin


def _copy_slots(target: AppSettings, source: AppSettings) -> None:
    for field in source.__dataclass_fields__:
        setattr(target, field, getattr(source, field))
