package it.mediaflow.atacroma.ui

import android.net.Uri
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DirectionsBus
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import it.mediaflow.atacroma.R
import it.mediaflow.atacroma.ui.screens.AlertsScreen
import it.mediaflow.atacroma.ui.screens.DeparturesScreen
import it.mediaflow.atacroma.ui.screens.StopsScreen

@Composable
fun AtacRomaApp() {
    val nav = rememberNavController()
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val showBottom = route == "stops" || route == "alerts"

    Scaffold(
        bottomBar = {
            if (showBottom) {
                NavigationBar {
                    NavigationBarItem(
                        selected = route == "stops",
                        onClick = {
                            if (route != "stops") nav.navigate("stops") {
                                popUpTo("stops") { inclusive = true }
                                launchSingleTop = true
                            }
                        },
                        icon = { Icon(Icons.Filled.DirectionsBus, null) },
                        label = { Text(stringResource(R.string.tab_stops)) },
                    )
                    NavigationBarItem(
                        selected = route == "alerts",
                        onClick = {
                            if (route != "alerts") nav.navigate("alerts") { launchSingleTop = true }
                        },
                        icon = { Icon(Icons.Filled.WarningAmber, null) },
                        label = { Text(stringResource(R.string.tab_alerts)) },
                    )
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = nav,
            startDestination = "stops",
            modifier = Modifier.padding(padding)
        ) {
            composable("stops") {
                StopsScreen(
                    onStopClick = { id -> nav.navigate("departures/${Uri.encode(id)}") }
                )
            }
            composable("alerts") {
                AlertsScreen()
            }
            composable(
                "departures/{stopId}",
                arguments = listOf(navArgument("stopId") { type = NavType.StringType })
            ) { entry ->
                val stopId = Uri.decode(entry.arguments?.getString("stopId").orEmpty())
                DeparturesScreen(stopId = stopId, onBack = { nav.popBackStack() })
            }
        }
    }
}
