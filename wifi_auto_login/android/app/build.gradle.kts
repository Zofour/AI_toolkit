plugins {
    id("com.android.application")
}

android {
    namespace = "com.chatbox.buctwifi"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.chatbox.buctwifi"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        resourceConfigurations += listOf("zh", "en")
    }

    buildTypes {
        getByName("debug") {
            isMinifyEnabled = false
            applicationIdSuffix = ""
        }
        getByName("release") {
            isMinifyEnabled = false
            // 用 debug 签名，方便直接侧载安装（自用工具，无需上架）
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

// 不引入任何 AndroidX 依赖：只用框架 API，编译最快、体积最小
dependencies {
}
