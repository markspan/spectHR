# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'form.ui'
##
## Created by: Qt User Interface Compiler version 6.9.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QHeaderView,
    QMainWindow, QMenu, QMenuBar, QScrollArea,
    QSizePolicy, QSplitter, QStatusBar, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(800, 600)
        self.actionOpen_Workspace = QAction(MainWindow)
        self.actionOpen_Workspace.setObjectName(u"actionOpen_Workspace")
        self.actionSettings = QAction(MainWindow)
        self.actionSettings.setObjectName(u"actionSettings")
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.splitter = QSplitter(self.centralwidget)
        self.splitter.setObjectName(u"splitter")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(1)
        sizePolicy.setHeightForWidth(self.splitter.sizePolicy().hasHeightForWidth())
        self.splitter.setSizePolicy(sizePolicy)
        self.splitter.setBaseSize(QSize(2, 0))
        self.splitter.setFrameShape(QFrame.Shape.VLine)
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.Treeframe = QFrame(self.splitter)
        self.Treeframe.setObjectName(u"Treeframe")
        self.Treeframe.setBaseSize(QSize(100, 0))
        self.Treeframe.setStyleSheet(u"background-color: #f3f3f3;")
        self.Treeframe.setFrameShape(QFrame.Shape.StyledPanel)
        self.Treeframe.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout = QHBoxLayout(self.Treeframe)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.treeWidget = QTreeWidget(self.Treeframe)
        __qtreewidgetitem = QTreeWidgetItem()
        __qtreewidgetitem.setText(0, u"1");
        self.treeWidget.setHeaderItem(__qtreewidgetitem)
        self.treeWidget.setObjectName(u"treeWidget")
        self.treeWidget.setRootIsDecorated(True)

        self.horizontalLayout.addWidget(self.treeWidget)

        self.splitter.addWidget(self.Treeframe)
        self.Views = QTabWidget(self.splitter)
        self.Views.setObjectName(u"Views")
        self.Views.setStyleSheet(u"background-color: #f3f3f3;")
        self.Views.setDocumentMode(True)
        self.PreProcessing = QWidget()
        self.PreProcessing.setObjectName(u"PreProcessing")
        self.horizontalLayout_2 = QHBoxLayout(self.PreProcessing)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.mplPreProcessing = QWidget(self.PreProcessing)
        self.mplPreProcessing.setObjectName(u"mplPreProcessing")

        self.horizontalLayout_2.addWidget(self.mplPreProcessing)

        self.Views.addTab(self.PreProcessing, "")
        self.Poincare = QWidget()
        self.Poincare.setObjectName(u"Poincare")
        self.horizontalLayout_3 = QHBoxLayout(self.Poincare)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.mplPoincare = QWidget(self.Poincare)
        self.mplPoincare.setObjectName(u"mplPoincare")

        self.horizontalLayout_3.addWidget(self.mplPoincare)

        self.Views.addTab(self.Poincare, "")
        self.Epochs = QWidget()
        self.Epochs.setObjectName(u"Epochs")
        self.horizontalLayout_4 = QHBoxLayout(self.Epochs)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.mplEpochs = QWidget(self.Epochs)
        self.mplEpochs.setObjectName(u"mplEpochs")

        self.horizontalLayout_4.addWidget(self.mplEpochs)

        self.Views.addTab(self.Epochs, "")
        self.Profiles = QWidget()
        self.Profiles.setObjectName(u"Profiles")
        self.horizontalLayout_5 = QHBoxLayout(self.Profiles)
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.mplProfiles = QWidget(self.Profiles)
        self.mplProfiles.setObjectName(u"mplProfiles")
        self.verticalLayout_2 = QVBoxLayout(self.mplProfiles)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.scrollArea = QScrollArea(self.mplProfiles)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 98, 28))
        self.scrollArea.setWidget(self.scrollAreaWidgetContents)

        self.verticalLayout_2.addWidget(self.scrollArea)


        self.horizontalLayout_5.addWidget(self.mplProfiles)

        self.Views.addTab(self.Profiles, "")
        self.splitter.addWidget(self.Views)

        self.verticalLayout.addWidget(self.splitter)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 800, 22))
        self.menufile = QMenu(self.menubar)
        self.menufile.setObjectName(u"menufile")
        self.menuView = QMenu(self.menubar)
        self.menuView.setObjectName(u"menuView")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menufile.menuAction())
        self.menubar.addAction(self.menuView.menuAction())
        self.menufile.addAction(self.actionOpen_Workspace)
        self.menuView.addAction(self.actionSettings)

        self.retranslateUi(MainWindow)

        self.Views.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.actionOpen_Workspace.setText(QCoreApplication.translate("MainWindow", u"Open Workspace", None))
        self.actionSettings.setText(QCoreApplication.translate("MainWindow", u"Settings", None))
        self.Views.setTabText(self.Views.indexOf(self.PreProcessing), QCoreApplication.translate("MainWindow", u"PreProcessing", None))
        self.Views.setTabText(self.Views.indexOf(self.Poincare), QCoreApplication.translate("MainWindow", u"Poincare", None))
        self.Views.setTabText(self.Views.indexOf(self.Epochs), QCoreApplication.translate("MainWindow", u"Epochs", None))
        self.Views.setTabText(self.Views.indexOf(self.Profiles), QCoreApplication.translate("MainWindow", u"Profiles", None))
        self.menufile.setTitle(QCoreApplication.translate("MainWindow", u"WorkSpace", None))
        self.menuView.setTitle(QCoreApplication.translate("MainWindow", u"View", None))
    # retranslateUi

