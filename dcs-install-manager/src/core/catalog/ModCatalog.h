#pragma once

#include <QList>
#include <QObject>
#include <QString>
#include <QVariantMap>

class ModEntry;

// Owns the mod/library/livery catalog: load/save catalog.json and CRUD. This is the
// single source of truth; ModCatalogModel is the QML-facing read model built on top
// of it.
class ModCatalog : public QObject
{
    Q_OBJECT

public:
    explicit ModCatalog(QObject *parent = nullptr);

    // Reads filePath into memory, replacing the current entries. Returns false (and
    // leaves the catalog untouched) if the file exists but fails to parse. A missing
    // file is not an error: the catalog is simply left/started empty.
    bool load(const QString &filePath);

    // Writes the current entries to filePath, creating parent directories as needed.
    bool save(const QString &filePath) const;

    const QList<ModEntry *> &entries() const;
    ModEntry *findById(const QString &id) const;

    ModEntry *addEntry(const QVariantMap &fields);
    bool updateEntry(const QString &id, const QVariantMap &fields);
    bool removeEntry(const QString &id);

signals:
    // Emitted after any add/update/remove/load so views can refresh.
    void catalogChanged();

private:
    QList<ModEntry *> m_entries;
};
