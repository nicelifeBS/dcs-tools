#pragma once

#include <QDateTime>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

class QJsonObject;

// One catalog entry: a mod, library, or livery, where it comes from, and where it
// installs to. See dcs-install-manager/data/catalog-schema.json for the JSON shape.
class ModEntry : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString id READ id CONSTANT)
    Q_PROPERTY(QString name READ name WRITE setName NOTIFY nameChanged)
    Q_PROPERTY(QString description READ description WRITE setDescription NOTIFY descriptionChanged)
    Q_PROPERTY(QString module READ module WRITE setModule NOTIFY moduleChanged)
    Q_PROPERTY(QString category READ category WRITE setCategory NOTIFY categoryChanged)
    Q_PROPERTY(QStringList tags READ tags WRITE setTags NOTIFY tagsChanged)
    Q_PROPERTY(QVariantMap source READ source WRITE setSource NOTIFY sourceChanged)
    Q_PROPERTY(QVariantList targets READ targets WRITE setTargets NOTIFY targetsChanged)
    Q_PROPERTY(bool needsReinstallAfterUpdate READ needsReinstallAfterUpdate WRITE
                   setNeedsReinstallAfterUpdate NOTIFY needsReinstallAfterUpdateChanged)
    Q_PROPERTY(QString notes READ notes WRITE setNotes NOTIFY notesChanged)
    Q_PROPERTY(QDateTime createdAt READ createdAt CONSTANT)
    Q_PROPERTY(QDateTime updatedAt READ updatedAt NOTIFY updatedAtChanged)

public:
    // Fixed v1 category enum, kept as plain strings so QML/JSON stay simple.
    static constexpr const char *CategoryAircraftLibrary = "aircraft-library";
    static constexpr const char *CategoryReinstallAfterUpdate = "reinstall-after-update";
    static constexpr const char *CategoryLivery = "livery";
    static constexpr const char *CategoryMisc = "misc";

    explicit ModEntry(const QString &id, QObject *parent = nullptr);

    QString id() const;

    QString name() const;
    void setName(const QString &name);

    QString description() const;
    void setDescription(const QString &description);

    QString module() const;
    void setModule(const QString &module);

    QString category() const;
    void setCategory(const QString &category);

    QStringList tags() const;
    void setTags(const QStringList &tags);

    // { "kind": "folder", "path": "..." } in v1.
    QVariantMap source() const;
    void setSource(const QVariantMap &source);

    // List of { installLocationKind, dcsVariant, relativePath, fileMappings }.
    QVariantList targets() const;
    void setTargets(const QVariantList &targets);

    bool needsReinstallAfterUpdate() const;
    void setNeedsReinstallAfterUpdate(bool needsReinstall);

    QString notes() const;
    void setNotes(const QString &notes);

    QDateTime createdAt() const;
    void setCreatedAt(const QDateTime &createdAt);

    QDateTime updatedAt() const;
    void setUpdatedAt(const QDateTime &updatedAt);

    // Applies whichever of the given fields are present (by key), leaving the rest
    // untouched. Used by ModCatalog::addEntry/updateEntry so callers can pass partial
    // field maps.
    void applyFields(const QVariantMap &fields);

    QJsonObject toJson() const;
    static ModEntry *fromJson(const QJsonObject &json, QObject *parent = nullptr);

signals:
    void nameChanged();
    void descriptionChanged();
    void moduleChanged();
    void categoryChanged();
    void tagsChanged();
    void sourceChanged();
    void targetsChanged();
    void needsReinstallAfterUpdateChanged();
    void notesChanged();
    void updatedAtChanged();

private:
    QString m_id;
    QString m_name;
    QString m_description;
    QString m_module;
    QString m_category = CategoryMisc;
    QStringList m_tags;
    QVariantMap m_source;
    QVariantList m_targets;
    bool m_needsReinstallAfterUpdate = false;
    QString m_notes;
    QDateTime m_createdAt;
    QDateTime m_updatedAt;
};
