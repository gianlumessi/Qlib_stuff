# Create a 5-year OIS swap using the OIS curve given below

# OIS zero curve  (continuously compounded, Act/365 Fixed).
# BBG Code of ESTR Swap curve: EESWE1. This is the index used for discounting in Bloomberg.
OIS_TENORS = ["1W", "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y"]
OIS_ZEROS  = [0.01931, 0.023711, 0.02448, 0.02475, 0.025132,
              0.02558, 0.0260515, 0.026589, 0.0271, 0.027626, 0.02814]

# Calculate the swap rate based on the OIS curve

# Calculate the swap present value. It should be 0.

# Change the 1-year rate by 1 bps (down) and re-calculate the swap value.

# Print the results