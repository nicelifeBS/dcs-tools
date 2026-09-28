cmake_minimum_required(VERSION 3.21)
project(DcsInstallManager LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

# LGPL Qt: this project must stay dynamically linked against Qt (windeployqt-style
# deployment, Qt DLLs shipped alongside the exe). Do not switch to a static Qt build
# without re-checking LGPL compliance for this project.
find_package(Qt6 REQUIRED COMPONENTS Core)

qt_standard_project_setup()

set(CORE_SOURCES
    src/core/catalog/ModEntry.h
    src/core/catalog/ModEntry.cpp
    src/core/catalog/ModCatalog.h
    src/core/catalog/ModCatalog.cpp
    src/core/catalog/ModCatalogModel.h
    src/core/catalog/ModCatalogModel.cpp
)

# No WIN32 flag yet: main.cpp is still a console smoke test (milestones 1-3), and
# WIN32 would suppress its console window on Windows. Add WIN32 back once the QML UI
# replaces it in milestone 4.
qt_add_executable(DcsInstallManager
    src/main.cpp
    ${CORE_SOURCES}
)

qt_add_resources(DcsInstallManager "data"
    PREFIX "/data"
    BASE data
    FILES data/default-catalog.json
)

target_link_libraries(DcsInstallManager PRIVATE Qt6::Core)
target_include_directories(DcsInstallManager PRIVATE src)

enable_testing()
add_subdirectory(tests)
