"""Stable model/view representation of incremental server results."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QBrush, QFont

from ..domain.models import ServerResult, ServerStatus
from ..theme import status_color

_INVALID_INDEX = QModelIndex()


class ResultsTableModel(QAbstractTableModel):
    COLUMNS = ("Server", "Endpoint", "Hits", "Status", "Detail")
    SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
    _STATUS_SORT_ORDER = {
        ServerStatus.SUCCESS: 0,
        ServerStatus.SEARCHING: 1,
        ServerStatus.PENDING: 2,
        ServerStatus.EMPTY: 3,
        ServerStatus.TIMED_OUT: 4,
        ServerStatus.FAILED: 5,
        ServerStatus.CANCELED: 6,
    }

    def __init__(self) -> None:
        super().__init__()
        self._results: list[ServerResult] = []
        self._rows: dict[str, int] = {}

    def rowCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX
    ) -> int:
        return 0 if parent.isValid() else len(self._results)

    def columnCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX
    ) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object | None:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object | None:
        if not index.isValid():
            return None
        result = self._results[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return result
        if role == self.SORT_ROLE:
            sort_values: tuple[object, ...] = (
                result.server.name.casefold(),
                result.server.endpoint.casefold(),
                result.number_of_hits if result.status == ServerStatus.SUCCESS else -1,
                self._STATUS_SORT_ORDER[result.status],
                result.message.casefold(),
            )
            return sort_values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return result.message or result.server.summary
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 2:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 3:
            return QBrush(status_color(result.status))
        if role == Qt.ItemDataRole.FontRole and index.column() == 3:
            font = QFont()
            font.setBold(True)
            return font
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        values: tuple[object, ...] = (
            result.server.name,
            result.server.endpoint,
            result.number_of_hits if result.status == ServerStatus.SUCCESS else "—",
            result.status.value,
            result.message,
        )
        return values[index.column()]

    def clear(self) -> None:
        self.beginResetModel()
        self._results.clear()
        self._rows.clear()
        self.endResetModel()

    def update_result(self, result: ServerResult) -> None:
        row = self._rows.get(result.server.id)
        if row is None:
            row = len(self._results)
            self.beginInsertRows(QModelIndex(), row, row)
            self._rows[result.server.id] = row
            self._results.append(result)
            self.endInsertRows()
            return
        self._results[row] = result
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, len(self.COLUMNS) - 1),
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ToolTipRole,
                Qt.ItemDataRole.ForegroundRole,
                Qt.ItemDataRole.FontRole,
                self.SORT_ROLE,
            ],
        )

    def refresh_theme(self) -> None:
        """Request a repaint so semantic cell colors follow an appearance change."""
        if self._results:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._results) - 1, len(self.COLUMNS) - 1),
                [Qt.ItemDataRole.ForegroundRole],
            )

    def result_at(self, row: int) -> ServerResult | None:
        return self._results[row] if 0 <= row < len(self._results) else None

    @property
    def available_count(self) -> int:
        return sum(result.status == ServerStatus.SUCCESS for result in self._results)
