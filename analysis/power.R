library(tidyverse)
library(miceadds)

# generate the synthetic data
gen_data <- function(
  num_classes,
  avg_num_students,
  student_fe_sd,
  test_sd,
  p_affected,
  mean_effect_for_affected,
  sd_effect_for_affected
  ) {
  
  # generate class sizes, fixed effects, and treatment assignments
  class_sizes <- rpois(num_classes, avg_num_students)
  class_fe <- rnorm(num_classes)
  treated <- rbinom(num_classes, 1, 0.5)
  num_students <- sum(class_sizes)
  
  # generate the data
  sim_data <- tibble(
    class_id = as.factor(rep(1:num_classes, class_sizes)),
    treated = rep(treated, class_sizes),
    class_fe = rep(class_fe, class_sizes),
    student_fe = student_fe_sd * rnorm(num_students),
    affected = rbinom(num_students, 1, p_affected),
    effect = affected * rnorm(num_students, mean_effect_for_affected, sd_effect_for_affected),
    pre_test = rnorm(num_students, class_fe + student_fe, test_sd),
    post_test = rnorm(num_students, class_fe + student_fe + treated*effect, test_sd)
  )
}

gen_sims <- function(
  num_sims,
  num_classes,
  avg_num_students,
  student_fe_sd,
  test_sd,
  p_affected,
  mean_effect_for_affected,
  sd_effect_for_affected
  ) {
  
  sim_result <- function() {
    # generate the data
    sim_data <- gen_data(
      num_classes = num_classes,
      avg_num_students = avg_num_students,
      student_fe_sd = student_fe_sd,
      test_sd = test_sd,
      p_affected = p_affected,
      mean_effect_for_affected = mean_effect_for_affected,
      sd_effect_for_affected = sd_effect_for_affected
    )
    
    # estimate effect
    model <- lm.cluster(post_test ~ treated + pre_test + class_id, 
                        cluster = 'class_id',
                        data = sim_data)
    
    treated_coef <- coef(model)['treated']
    treated_se <- sqrt(vcov(model)['treated', 'treated'])
    treated_t <- treated_coef / treated_se
    
    results <- tibble(
      treated_coef = treated_coef,
      treated_se = treated_se,
      treated_t = treated_t
    )
  }
  
 results <- map_dfr(1:num_sims, ~sim_result())
}

# run the simulations
sims <- gen_sims(
  num_sims = 100,
  num_classes = 200,
  avg_num_students = 50,
  student_fe_sd = 1,
  test_sd = 0.5,
  p_affected = 0.5,
  mean_effect_for_affected = 0.5,
  sd_effect_for_affected = 0.25
)

# compute power
power <- sims %>%
  summarise(
    coef = mean(treated_coef),
    power = mean(treated_t > 2)
  )

